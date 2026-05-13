# =============================================================================
# [MODIFIED HCI - 2026-05-12]
# Modifiche apportate (Milestone 3 - Ottimizzazione):
#   1. ASSORBITA la logica RAG ricca e contestuale.
#   2. FIX CRASH: Gestione sicura cronologia vuota.
#   3. FSM GATEKEEPER: Ora le risposte ai blocchi sono DETERMINISTICHE.
#   4. FIX BUG CHAT HISTORY: Ancoraggio esplicito allo stato del DB.
#   5. FIX BUG ANTI-LOOP: Ereditata logica di shake.py per il fallback.
#   6. FIX VOCALE: Obbligo di pronunciare Kcal e Durata.
#   7. FIX CATALOGO: Ora Minerva pesca SOLO dagli hobby preferiti dell'utente (NON globale).
#   8. FIX RIFIUTO RAPIDO: Regola rigida per forzare action="REJECT" se l'utente dice no.
#   9. FIX ESAURIMENTO HOBBY: Se tutte le attività sono state rifiutate, scatta la pausa forzata.
# =============================================================================

import os
import json
import uuid
import logging
import re
from datetime import date, datetime
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.voice.models import VoiceRequest, VoiceResponse

router = APIRouter(prefix="/users/{user_id}/voice", tags=["Voice Assistant"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def safe_int(val, default=0):
    try:
        if isinstance(val, int): return val
        nums = re.findall(r'\d+', str(val))
        return int(nums[0]) if nums else default
    except:
        return default

@router.post("", response_model=VoiceResponse)
def generate_voice_response(user_id: str, request: VoiceRequest, conn: mariadb.Connection = Depends(db_connection)):
    if not GEMINI_API_KEY:
        return VoiceResponse(text="Attenzione, la chiave API di Gemini è mancante nel server.")

    today_str = date.today().isoformat()

    try:
        execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'user', ?)",
                      (user_id, request.message), fetch=False)
    except Exception as e:
        logging.error(f"Errore salvataggio chat: {e}")

    # 1. RECUPERO CONTESTO AMBIENTALE (Beacon attivo)
    presence = execute_query(conn, """
        SELECT z.beacon_id, b.zone_name, b.associated_hobby_id, z.entry_timestamp 
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND z.exit_timestamp IS NULL
        ORDER BY z.entry_timestamp DESC LIMIT 1
    """, (user_id,), fetchone=True, dict=True)

    zone_context = "L'utente non è in una zona tracciata al momento."
    room_hobby_name = None
    beacon_id_val = None
    
    if presence:
        beacon_id_val = presence['beacon_id']
        entry_ts = presence['entry_timestamp']
        if isinstance(entry_ts, str):
            try: entry_ts = datetime.fromisoformat(entry_ts)
            except: pass
        if isinstance(entry_ts, datetime):
            minutes = int((datetime.now() - entry_ts).total_seconds() / 60)
            zone_context = f"L'utente si trova in '{presence['zone_name']}' da {minutes} minuti."
            
        # FIX ANTI-LOOP: Controlla se l'hobby della stanza è valido o già rifiutato
        if presence.get('associated_hobby_id'):
            assoc_hobby = presence['associated_hobby_id']
            user_pref = execute_query(conn, """
                SELECT preference_level 
                FROM user_hobbies 
                WHERE user_id = ? AND hobby_id = ?
            """, (user_id, assoc_hobby), fetchone=True, dict=True)
            
            if user_pref and user_pref['preference_level'] > 2:
                already_rejected = execute_query(conn, """
                    SELECT 1 FROM activity_suggestions 
                    WHERE user_id = ? AND hobby_id = ? AND status = 'REJECTED' AND DATE(created_at) = CURDATE()
                """, (user_id, assoc_hobby), fetchone=True)
                
                if not already_rejected:
                    h_info = execute_query(conn, "SELECT hobby_name FROM hobbies_catalog WHERE hobby_id = ?", 
                                           (assoc_hobby,), fetchone=True, dict=True)
                    room_hobby_name = f"{h_info['hobby_name']} (ID: {assoc_hobby})" if h_info else None
                else:
                    room_hobby_name = None
            else:
                room_hobby_name = None 

    # =========================================================================
    # FIX CATALOGO: Pesca SOLO le attività preferite non ancora rifiutate
    # =========================================================================
    user_available_hobbies = execute_query(conn, """
        SELECT h.hobby_id, h.hobby_name 
        FROM user_hobbies uh
        JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
        WHERE uh.user_id = ?
        AND uh.preference_level > 2
        AND NOT EXISTS (
            SELECT 1 FROM activity_suggestions a
            WHERE a.hobby_id = uh.hobby_id 
            AND a.user_id = uh.user_id 
            AND a.status = 'REJECTED' 
            AND DATE(a.created_at) = CURDATE()
        )
    """, (user_id,), dict=True)

    if not user_available_hobbies:
        catalog_context = "NESSUN HOBBY DISPONIBILE (Tutti rifiutati per oggi)."
    else:
        catalog_context = ", ".join([f"{h['hobby_name']} (ID: {h['hobby_id']})" for h in user_available_hobbies])

    # Fallback logica shake: se la stanza non ha hobby validi, pesca il migliore dalla lista
    if not room_hobby_name and user_available_hobbies:
        hobby_data = execute_query(conn, """
            SELECT h.hobby_id, h.hobby_name 
            FROM user_hobbies uh
            JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
            WHERE uh.user_id = ?
            AND uh.preference_level > 2
            AND NOT EXISTS (
                SELECT 1 FROM activity_suggestions a
                WHERE a.hobby_id = uh.hobby_id 
                AND a.user_id = uh.user_id 
                AND a.status = 'REJECTED' 
                AND DATE(a.created_at) = CURDATE()
            )
            ORDER BY uh.preference_level DESC LIMIT 1
        """, (user_id,), fetchone=True, dict=True)
        if hobby_data:
            room_hobby_name = f"{hobby_data['hobby_name']} (ID: {hobby_data['hobby_id']})"

    # 2. IL CANCELLO DI CONTROLLO (FSM)
    try:
        execute_query(conn, "CALL EvaluateProactiveState(?, ?, @out_state)", (user_id, beacon_id_val), fetch=False)
        fsm_res = execute_query(conn, "SELECT @out_state as state", fetchone=True, dict=True)
        fsm_state = fsm_res['state'] if fsm_res and fsm_res['state'] else "TRIGGER_FITNESS"
    except Exception as e:
        logging.error(f"Errore FSM: {e}")
        fsm_state = "TRIGGER_FITNESS"

    # 3. Recupero dati utente
    user_data = execute_query(conn, "SELECT weight_kg, daily_kcal_goal FROM users WHERE user_id = ?", (user_id,), fetchone=True, dict=True)
    if not user_data: 
        return VoiceResponse(text="Scusami, non riesco a trovare il tuo profilo nel sistema.")

    kcal_logs = execute_query(conn, "SELECT SUM(kcal_burned) as total FROM biometric_logs WHERE user_id = ? AND record_date = ?", 
                              (user_id, today_str), fetchone=True, dict=True)
    
    daily_goal = user_data.get('daily_kcal_goal', 2000)
    kcal_burned_today = kcal_logs['total'] if kcal_logs and kcal_logs['total'] is not None else 0
    kcal_mancanti = max(0, daily_goal - kcal_burned_today)

    pending_act = execute_query(conn, """
        SELECT suggestion_id, status FROM activity_suggestions 
        WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = ?
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, today_str), fetchone=True, dict=True)

    history_raw = execute_query(conn, "SELECT sender_role, message_content FROM chat_history WHERE user_id = ? ORDER BY message_timestamp DESC LIMIT 5", (user_id,), dict=True)
    if not history_raw: history_raw = []
    chat_context = "\n".join([f"{m['sender_role']}: {m['message_content']}" for m in reversed(history_raw)])

    db_state_info = ""
    if pending_act:
        db_state_info = f"L'utente HA un'attività in sospeso (Status: {pending_act['status']})."
    else:
        db_state_info = "ATTENZIONE: L'utente NON HA attualmente nessuna attività in sospeso."

    # =========================================================================
    # PROMPT GEMINI: Aggiunta regola "Tolleranza Zero" per il Rifiuto
    # =========================================================================
    system_prompt = f"""
    Sei Minerva, l'assistente vocale di FlowMate. Parla in modo naturale, breve e incoraggiante.
    
    CONTESTO ATTUALE:
    - {zone_context}
    - Hobby suggerito dal sistema per questa interazione: {room_hobby_name or "Nessuno specifico"}.
    - CATALOGO HOBBY PERSONALE DELL'UTENTE (Usa SOLO questi ID): {catalog_context}
    - Obiettivo: {daily_goal} kcal. Bruciate: {kcal_burned_today} kcal. Mancano: {kcal_mancanti} kcal.
    - STATO REALE DEL DATABASE: {db_state_info}
    - Cronologia Chat: {chat_context}

    REGOLE RIGIDE:
    1. MASSIMA CONCISIONE: Parla come un compagno di allenamento in 1 o 2 frasi.
    2. CAPISCI AL VOLO L'ACCETTAZIONE: Se c'è un'attività in sospeso e l'utente usa parole come "accetto", "sì", "va bene", "ok", "facciamolo", DEVI obbligatoriamente restituire action="ACCEPT".
    3. CAPISCI AL VOLO IL RIFIUTO: Se c'è un'attività in sospeso e l'utente usa parole come "rifiuto", "no", "cambia", "non mi va", DEVI obbligatoriamente restituire action="REJECT".
    4. STIMA CALORIE E DURATA (FONDAMENTALE): Se proponi un'attività, inserisci SEMPRE nel testo parlato i minuti previsti e le calorie.
    5. INSERIMENTO ID: Se decidi di fare una proposta (action="PROPOSE"), DEVI inserire in "hobby_id" l'ID numerico letto dal CATALOGO HOBBY PERSONALE.
    RITORNA ESCLUSIVAMENTE QUESTO JSON:
    {{
        "text": "risposta vocale",
        "action": "ACCEPT" | "REJECT" | "PROPOSE" | null,
        "hobby_id": ID (intero) o null,
        "duration": minuti (intero) o null,
        "kcal": stima kcal (intero) o null
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content([system_prompt, request.message])
        ai_data = json.loads(response.text)
    except Exception as e:
        logging.error(f"Errore generazione Gemini: {e}")
        ai_data = {"text": "Scusami, ho perso la connessione per un istante.", "action": None}

    ai_text = str(ai_data.get("text", ai_data.get("response", ai_data.get("message", "Non ho capito."))))
    action = str(ai_data.get("action", "")).upper() if ai_data.get("action") else None
    hobby_id = safe_int(ai_data.get("hobby_id"), None)

    # =========================================================================
    # 5. SOVRASCRITTURA DETERMINISTICA E PAUSA FORZATA
    # =========================================================================
    if action == "PROPOSE":
        if not user_available_hobbies:
            ai_text = "Pausa forzata! 😅 Hai scartato tutte le tue attività preferite per oggi. Goditi il riposo!"
            action = None
        elif pending_act:
            if pending_act['status'] == 'PROPOSED':
                ai_text = "Hai già una proposta in attesa! Controlla il tablet e dimmi se accetti o rifiuti."
                action = None
            elif pending_act['status'] == 'ACCEPTED':
                ai_text = "Guarda che devi finire ancora la tua attività prima di chiedermi altro!"
                action = None
        elif fsm_state != "TRIGGER_FITNESS":
            if fsm_state == 'SILENT_USER_OPTED_OUT':
                ai_text = "Hai impostato lo stop per oggi. Non ti proporrò nient'altro, goditi il relax!"
            elif fsm_state == 'SILENT_BUSY_SCHEDULE':
                ai_text = "Sei nel tuo orario di non disturbo. Torna da me più tardi!"
            elif fsm_state == 'SILENT_COOLDOWN':
                ai_text = "Hai appena rifiutato un'attività. Prenditi una pausa, ci riproviamo tra mezz'ora!"
            elif fsm_state == 'SILENT_ZONE_DISABLED':
                ai_text = "Le notifiche sono disabilitate per questa stanza. Spostati o riattivale per avere consigli."
            action = None

    # 6. Esecuzione Azioni Database
    try:
        if action == "ACCEPT" and pending_act:
            execute_query(conn, "UPDATE activity_suggestions SET status = 'ACCEPTED' WHERE suggestion_id = ?", 
                          (pending_act['suggestion_id'],), fetch=False)
            logging.info("Azione ACCEPT eseguita con successo sul DB.")
            
        elif action == "REJECT" and pending_act:
            execute_query(conn, "UPDATE activity_suggestions SET status = 'REJECTED', rejection_reason = 'dislike' WHERE suggestion_id = ?", 
                          (pending_act['suggestion_id'],), fetch=False)
            logging.info("Azione REJECT (dislike) eseguita con successo sul DB.")
            
        elif action == "PROPOSE" and hobby_id:
            execute_query(conn, "UPDATE activity_suggestions SET status = 'REJECTED' WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = ?", (user_id, today_str), fetch=False)
            suggestion_id = str(uuid.uuid4())
            
            safe_duration = safe_int(ai_data.get('duration'), 20)
            safe_kcal = safe_int(ai_data.get('kcal'), 100)
            
            execute_query(conn, """
                INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
                VALUES (?, ?, ?, ?, ?, 'PROPOSED')
            """, (suggestion_id, user_id, hobby_id, safe_duration, safe_kcal), fetch=False)

        execute_query(conn, "INSERT INTO chat_history (user_id, sender_role, message_content) VALUES (?, 'assistant', ?)",
                      (user_id, ai_text), fetch=False)
    except Exception as e:
        logging.error(f"Errore DB in fase di azione AI: {e}")

    return VoiceResponse(text=ai_text)