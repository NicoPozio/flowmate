import os
import json
import uuid
import logging
from datetime import date
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.chat.models import ChatRequest, ChatResponse, Option

router = APIRouter(prefix="/users/{user_id}", tags=["Chat & AI Suggestions"])

# Inizializzazione Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# =====================================================================
# 1. ENDPOINT PRINCIPALE: CHATBOT
# =====================================================================
@router.post("/chat", response_model=ChatResponse)
def generate_ai_suggestion(user_id: str, request: ChatRequest, conn: mariadb.Connection = Depends(db_connection)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API Key non configurata.")

    user_data = execute_query(conn, "SELECT weight_kg, daily_kcal_goal FROM users WHERE user_id = ?", (user_id,), fetchone=True, dict=True)
    if not user_data:
        raise HTTPException(status_code=404, detail=f"Utente {user_id} non trovato.")

    execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'user', ?)", 
                  (user_id, request.message), fetch=False)

    hobbies_raw = execute_query(conn, """
        SELECT h.hobby_id, h.hobby_name, h.met_value, uh.preference_level 
        FROM user_hobbies uh
        JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
        WHERE uh.user_id = ?
        ORDER BY uh.preference_level DESC
    """, (user_id,), dict=True)
    
    hobbies_list = hobbies_raw if hobbies_raw else [{"hobby_name": "Passeggiata", "preference_level": 5, "met_value": 3.5}]

    today_str = date.today().isoformat()
    kcal_logs = execute_query(conn, """
        SELECT SUM(kcal_burned) as total_burned 
        FROM biometric_logs 
        WHERE user_id = ? AND record_date = ?
    """, (user_id, today_str), fetchone=True, dict=True)
    
    daily_goal = user_data.get('daily_kcal_goal', 2000)
    kcal_burned_today = kcal_logs['total_burned'] if kcal_logs and kcal_logs['total_burned'] is not None else 0
    
    kcal_mancanti = daily_goal - kcal_burned_today
    if kcal_mancanti < 0:
        kcal_mancanti = 0

    # =========================================================================
    # NEW: FETCH TODAY'S ACTIVITY SUGGESTIONS
    # =========================================================================
    daily_activities_raw = execute_query(conn, """
        SELECT a.status, a.suggested_duration_minutes, h.hobby_name
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        WHERE a.user_id = ? AND DATE(a.created_at) = ?
        ORDER BY a.created_at DESC
    """, (user_id, today_str), dict=True)

    activities_context = "Nessuna attività proposta oggi."
    if daily_activities_raw:
        activities_context = ""
        for act in daily_activities_raw:
            activities_context += f"- {act['hobby_name']} ({act['suggested_duration_minutes']} min): Stato -> {act['status']}\n"
    # =========================================================================

    history_raw = execute_query(conn, """
        SELECT sender_role, message_content 
        FROM chat_history 
        WHERE user_id = ? 
        ORDER BY message_timestamp DESC LIMIT 5
    """, (user_id,), dict=True)
    
    chat_context = ""
    for msg in reversed(history_raw if history_raw else []):
        role = "Utente" if msg['sender_role'] == 'user' else "FlowMate"
        chat_context += f"{role}: {msg['message_content']}\n"

    # --- MODIFICA AL PROMPT: AGGIUNTO IL CONTROLLO SULLE ATTIVITÀ DI OGGI ---
    system_prompt = f"""
    Sei FlowMate, un assistente fitness empatico e amichevole.
    
    DATI UTENTE IN TEMPO REALE:
    - Peso: {user_data['weight_kg']}kg
    - Obiettivo Giornaliero: {daily_goal} kcal
    - Calorie Bruciate Oggi: {kcal_burned_today} kcal
    - CALORIE MANCANTI ALL'OBIETTIVO: {kcal_mancanti} kcal
    
    STATO DELLE ATTIVITÀ DI OGGI:
    {activities_context}
    
    Hobby e Preferenze:
    {hobbies_list}
    
    Cronologia:
    {chat_context}
    
    REGOLE DI CONVERSAZIONE E GESTIONE ATTIVITÀ:
    1. CONTROLLO STATUS: Controlla sempre lo "STATO DELLE ATTIVITÀ DI OGGI" prima di rispondere.
       - Se l'utente ha un'attività in stato "PROPOSED": NON FARE NUOVE PROPOSTE (restituisci hobby_id: null). Chiedigli se ha intenzione di accettare o rifiutare l'attività che gli hai appena suggerito.
       - Se l'utente ha un'attività in stato "ACCEPTED": Ricordagli in modo incoraggiante che ha quell'attività in sospeso. 
         TUTTAVIA, se l'utente dice chiaramente che non vuole più farla, che ha cambiato idea o chiede esplicitamente un'altra proposta, 
         ALLORA puoi proporre un nuovo hobby (impostando hobby_id, duration e kcal).
       -Se l'utente ha un'attività in stato "COMPLETED": Fagli molti complimenti! ATTENZIONE: le "Calorie Bruciate Oggi" indicano il totale della giornata, NON quelle della singola attività. Specifica sempre usando frasi come "Fino ad ora hai bruciato un totale di {kcal_burned_today} kcal oggi". Proponi un'altra attività solo se gli mancano ancora calorie per raggiungere l'obiettivo.
    2. SALUTI E CHIACCHIERE: Se l'utente dice "Ciao" o "Bene", fai conversazione MA concludi SEMPRE con uno sprono amichevole. NON inserire l'hobby_id in questa fase.
    3. QUANDO PROPORRE: Fai una proposta ufficiale (impostando un hobby_id valido) solo se non ci sono attività "ACCEPTED" in sospeso e se l'utente è pronto ad allenarsi.
    4. REGOLA DELLE CALORIE (FONDAMENTALE): Ogni volta che fai una proposta ufficiale, DEVI scrivere esplicitamente nel messaggio testuale quante calorie brucerà (es. "Ti propongo una passeggiata di 30 minuti, brucerai circa 150 kcal!").
    5. DOPO UN'ACCETTAZIONE O RIFIUTO: Fai il tifo per lui o rassicuralo, poi FERMATI. Non fare altre proposte immediate.
    
    RITORNA SEMPRE E SOLO QUESTO JSON:
    {{
        "text": "il tuo messaggio",
        "hobby_id": ID_DELL_HOBBY (inserisci null se stai solo chiacchierando o ricordando un'attività in sospeso),
        "duration": MINUTI (inserisci null se non fai nuove proposte),
        "kcal": CALORIE_STIMATE (inserisci null se non fai nuove proposte),
        "is_off_topic": false
    }}
    """

    try:
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content([system_prompt, request.message])
        ai_data = json.loads(response.text)
    except Exception as e:
        logging.error(f"Gemini Error dettagliato: {e}")
        ai_data = {"text": "Scusa, ho avuto un piccolo problema. Possiamo riprovare?", "is_off_topic": True}

    execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'assistant', ?)", 
                  (user_id, ai_data.get('text', "")), fetch=False)

    options = []
    suggestion_id = None

    if not ai_data.get("is_off_topic", False) and ai_data.get("hobby_id") is not None:
        # --- NOVITÀ: PULIZIA DATABASE ---
        # Prima di inserire la nuova proposta, mettiamo in REJECTED tutto quello 
        # che era PROPOSED o ACCEPTED per oggi, così non abbiamo conflitti.
        execute_query(conn, """
            UPDATE activity_suggestions 
            SET status = 'REJECTED' 
            WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = ?
        """, (user_id, today_str), fetch=False)

        # Ora inseriamo la nuova proposta come prima
        suggestion_id = str(uuid.uuid4())
        execute_query(conn, """
            INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
            VALUES (?, ?, ?, ?, ?, 'PROPOSED')
        """, (suggestion_id, user_id, ai_data.get('hobby_id'), ai_data.get('duration', 20), ai_data.get('kcal', 100)), fetch=False)
        
        options = [
            {"action": "ACCEPT", "label": "✅ Accetta"},
            {"action": "REJECT", "label": "❌ No grazie"}
        ]

    return ChatResponse(message_id=str(uuid.uuid4()), text=ai_data.get('text', ""), suggestion_id=suggestion_id, options=[Option(**opt) for opt in options])

@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(user_id: str, suggestion_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    
    # 1. Trova i minuti attivi attuali dell'utente
    current_logs = execute_query(conn, """
        SELECT SUM(active_minutes) as current_active 
        FROM biometric_logs 
        WHERE user_id = ? AND record_date = ?
    """, (user_id, today_str), fetchone=True, dict=True)
    
    baseline_minutes = current_logs['current_active'] if current_logs and current_logs['current_active'] is not None else 0

    # 2. Aggiorna lo stato in ACCEPTED e salva la fotografia iniziale (baseline)
    execute_query(conn, """
        UPDATE activity_suggestions 
        SET status = 'ACCEPTED', baseline_active_minutes = ?
        WHERE suggestion_id = ? AND user_id = ?
    """, (baseline_minutes, suggestion_id, user_id), fetch=False)
    
    return {"status": "success", "message": "Attività accettata, snapshot registrato."}

# --- NUOVO ENDPOINT: AGGIORNA STATO IN "REJECTED" ---
@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(user_id: str, suggestion_id: str, conn: mariadb.Connection = Depends(db_connection)):
    execute_query(conn, "UPDATE activity_suggestions SET status = 'REJECTED' WHERE suggestion_id = ? AND user_id = ?", (suggestion_id, user_id), fetch=False)
    return {"status": "success", "message": "Attività rifiutata"}