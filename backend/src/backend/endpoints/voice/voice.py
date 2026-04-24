import os
import json
import logging
from datetime import date
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
import mariadb
from db.mariadb import db_connection, execute_query

from endpoints.voice.models import VoiceRequest, VoiceResponse

router = APIRouter(prefix="/users/{user_id}", tags=["Voice Assistant"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@router.post("/voice", response_model=VoiceResponse)
def generate_voice_response(user_id: str, request: VoiceRequest, conn: mariadb.Connection = Depends(db_connection)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API Key non configurata.")

    # 1. Recupero dati utente e calorie
    user_data = execute_query(conn, "SELECT weight_kg, daily_kcal_goal FROM users WHERE user_id = ?", (user_id,), fetchone=True, dict=True)
    today_str = date.today().isoformat()
    kcal_logs = execute_query(conn, "SELECT SUM(kcal_burned) as total_burned FROM biometric_logs WHERE user_id = ? AND record_date = ?", (user_id, today_str), fetchone=True, dict=True)
    
    daily_goal = user_data.get('daily_kcal_goal', 2000)
    kcal_burned_today = kcal_logs['total_burned'] if kcal_logs and kcal_logs['total_burned'] is not None else 0
    kcal_mancanti = max(0, daily_goal - kcal_burned_today)

    # 2. CONTROLLO ATTIVITÀ PENDENTE (Nuova Logica)
    # Cerchiamo se esiste una proposta 'PROPOSED' o 'ACCEPTED' fatta oggi
    pending_act = execute_query(conn, """
        SELECT a.suggestion_id, a.status, h.hobby_name, a.suggested_duration_minutes
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        WHERE a.user_id = ? AND a.status IN ('PROPOSED', 'ACCEPTED') AND DATE(a.created_at) = ?
        ORDER BY a.created_at DESC LIMIT 1
    """, (user_id, today_str), fetchone=True, dict=True)

    status_context = "Nessuna attività pendente."
    if pending_act:
        status_context = f"L'utente ha una proposta di {pending_act['hobby_name']} in stato {pending_act['status']}."

    # 3. SYSTEM PROMPT EVOLUTO
    # Chiediamo a Gemini di decidere se l'utente sta accettando o rifiutando
    system_prompt = f"""
        Sei FlowMate, un Personal Trainer motivatore. 
        Il tuo obiettivo è aiutare l'utente a BRUCIARE le calorie rimanenti per raggiungere il suo target giornaliero.

        DATI CORRENTI:
        - Obiettivo Totale da Bruciare: {daily_goal} kcal
        - Calorie già bruciate: {kcal_burned_today} kcal
        - GAP DA COLMARE: {kcal_mancanti} kcal

        LOGICA DI RISPOSTA:
        1. Se l'utente chiede una nuova attività e il GAP è > 0: 
        Scegli un hobby tra quelli dell'utente e proponi una durata che aiuti a colmare il gap.
        2. NON suggerire mai di mangiare o fare pasti. Tu ti occupi solo di MOVIMENTO.
        3. Se non ci sono attività pendenti nel DB, CREANE UNA NUOVA parlandone all'utente.
        """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content([system_prompt, request.message])
        ai_data = json.loads(response.text)
    except Exception as e:
        ai_data = {"text": "Errore di connessione.", "action": None}

    # 4. AGGIORNAMENTO DB IN BASE ALLA RISPOSTA (Logica Sync con chat.py)
    action = ai_data.get("action")
    if action and pending_act:
        if action == "ACCEPT" and pending_act['status'] == 'PROPOSED':
            # Snapshot dei minuti active come in chat.py
            current_active = execute_query(conn, "SELECT SUM(active_minutes) as mins FROM biometric_logs WHERE user_id = ? AND record_date = ?", (user_id, today_str), fetchone=True, dict=True)
            baseline = current_active['mins'] if current_active['mins'] else 0
            
            execute_query(conn, "UPDATE activity_suggestions SET status = 'ACCEPTED', baseline_active_minutes = ? WHERE suggestion_id = ?", 
                          (baseline, pending_act['suggestion_id']), fetch=False)
            
        elif action == "REJECT":
            execute_query(conn, "UPDATE activity_suggestions SET status = 'REJECTED' WHERE suggestion_id = ?", 
                          (pending_act['suggestion_id'],), fetch=False)

    # 5. Salva in cronologia
    execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'assistant', ?)", 
                  (user_id, ai_data.get('text', "")), fetch=False)

    return VoiceResponse(text=ai_data.get('text', ""))