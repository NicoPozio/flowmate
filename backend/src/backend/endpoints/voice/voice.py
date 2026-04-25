import os
import json
import uuid
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

    # 2. Recupero Hobby (Fondamentale per fare nuove proposte)
    hobbies_raw = execute_query(conn, """
        SELECT h.hobby_id, h.hobby_name, h.met_value, uh.preference_level 
        FROM user_hobbies uh
        JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
        WHERE uh.user_id = ?
        ORDER BY uh.preference_level DESC
    """, (user_id,), dict=True)
    
    hobbies_list = hobbies_raw if hobbies_raw else [{"hobby_id": 1, "hobby_name": "Passeggiata", "preference_level": 5, "met_value": 3.5}]

    # 3. Controllo attività pendente
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

    # 4. Prompt Ottimizzato per Vocale (con creazione proposte)
    # 4. Prompt Ottimizzato per Vocale (con correzione errori STT)
    system_prompt = f"""
    Sei FlowMate, un Personal Trainer motivatore. Questa è un'interfaccia VOCALE.
    Le tue risposte verranno lette ad alta voce. Devono essere CONCISE, dirette e colloquiali (massimo 2 frasi). Niente elenchi.

    DATI CORRENTI:
    - GAP DA COLMARE: {kcal_mancanti} kcal
    - STATO: {status_context}
    - HOBBY UTENTE: {hobbies_list}

    LOGICA:
    1. Se lo STATO dice che c'è una proposta in stato "PROPOSED", l'utente deve rispondere.
       ATTENZIONE: Il microfono fa spesso errori di trascrizione. Se l'utente dice frasi o parole di assenso anche storpiate (es. "accendo", "accetto", "certo", "ok", "va bene", "a letto", "sì"), interpretalo SEMPRE come un'accettazione e metti "action": "ACCEPT".
       Se dice parole di diniego (es. "no", "rifiuto", "non mi va", "basta"), metti "action": "REJECT".
    2. Se l'utente accetta o rifiuta, metti la action corrispondente nel JSON e imposta hobby_id a null.
    3. Se NON ci sono pendenze, proponi un HOBBY dalla sua lista.
    4. Se lo STATO dice "ACCEPTED": l'utente ha già un'attività in programma per oggi! Fagli i complimenti e ricordagli di farla. NON proporre nulla di nuovo (imposta "hobby_id" a null e "action" a null).

    RITORNA SEMPRE E SOLO QUESTO FORMATO JSON:
    {{
        "text": "la tua risposta vocale brevissima",
        "action": "ACCEPT" oppure "REJECT" oppure null,
        "hobby_id": ID_DELL_HOBBY (oppure null),
        "duration": MINUTI (oppure null),
        "kcal": CALORIE_STIMATE (oppure null)
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content([system_prompt, request.message])
        print(f"DEBUG GEMINI RAW RESPONSE: {response.text}") 
        ai_data = json.loads(response.text)
    except Exception as e:
        logging.error(f"Gemini JSON Error: {e}")
        ai_data = {"text": "Scusa, non ho capito bene. Riprova.", "action": None, "hobby_id": None}

    # 5. Esecuzione Azioni DB
    action = ai_data.get("action")
    hobby_id = ai_data.get("hobby_id")

    # Caso A: L'utente ha accettato/rifiutato un'attività esistente
    if action and pending_act:
        if action == "ACCEPT" and pending_act['status'] == 'PROPOSED':
            current_active = execute_query(conn, "SELECT SUM(active_minutes) as mins FROM biometric_logs WHERE user_id = ? AND record_date = ?", (user_id, today_str), fetchone=True, dict=True)
            baseline = current_active['mins'] if current_active['mins'] else 0
            execute_query(conn, "UPDATE activity_suggestions SET status = 'ACCEPTED', baseline_active_minutes = ? WHERE suggestion_id = ?", 
                          (baseline, pending_act['suggestion_id']), fetch=False)
            
        elif action == "REJECT":
            execute_query(conn, "UPDATE activity_suggestions SET status = 'REJECTED' WHERE suggestion_id = ?", 
                          (pending_act['suggestion_id'],), fetch=False)

    # Caso B: Creazione di una NUOVA proposta (se non c'è nulla in sospeso)
    elif not pending_act and hobby_id is not None:
        suggestion_id = str(uuid.uuid4())
        duration = ai_data.get('duration', 30)
        kcal = ai_data.get('kcal', 150)
        
        execute_query(conn, """
            INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
            VALUES (?, ?, ?, ?, ?, 'PROPOSED')
        """, (suggestion_id, user_id, hobby_id, duration, kcal), fetch=False)

    # 6. Salvataggio in cronologia
    execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'assistant', ?)", 
                  (user_id, ai_data.get('text', "")), fetch=False)

    return VoiceResponse(text=ai_data.get('text') or "Non ho nulla da dire al momento.")