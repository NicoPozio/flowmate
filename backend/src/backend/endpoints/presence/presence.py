# src/backend/endpoints/presence/presence.py

import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
import mariadb
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from db.mariadb import db_connection, execute_query

# Importa il worker per le notifiche
from notifications.push_service import send_proactive_notification_task

router = APIRouter(prefix="/users/{user_id}/presence", tags=["Presence Tracking"])

# --- Models ---
class PresenceEntryRequest(BaseModel):
    beacon_id: str

class PresenceLog(BaseModel):
    presence_id: str
    user_id: str
    beacon_id: str
    entry_timestamp: datetime
    exit_timestamp: Optional[datetime] = None
    duration_minutes: Optional[int] = None

class PresenceEntryResponse(BaseModel):
    log: dict
    action_state: str
    intent: Optional[str] = None

# --- Endpoints ---
@router.post("/entry", response_model=PresenceEntryResponse, status_code=status.HTTP_201_CREATED)
def log_presence_entry(
    user_id: str, 
    req: PresenceEntryRequest, 
    background_tasks: BackgroundTasks,
    conn: mariadb.Connection = Depends(db_connection)
):
    """
    Apertura sessione di permanenza e valutazione FSM (Macchina a Stati).
    """
    # 1. Verifica validita' Beacon
    check_beacon = execute_query(conn, "SELECT beacon_id FROM beacons_catalog WHERE beacon_id = ?", (req.beacon_id,), fetchone=True)
    if not check_beacon:
        raise HTTPException(status_code=400, detail="Invalid beacon_id")

    # 2. Registra l'ingresso logico
    new_presence_id = str(uuid.uuid4())
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    insert_query = """
        INSERT INTO zone_presence_logs (presence_id, user_id, beacon_id, entry_timestamp)
        VALUES (?, ?, ?, ?)
    """
    execute_query(conn, insert_query, (new_presence_id, user_id, req.beacon_id, now_str), fetch=False)
    
    presence_data = execute_query(conn, "SELECT * FROM zone_presence_logs WHERE presence_id = ?", (new_presence_id,), fetchone=True, dict=True)

    # 3. INTERROGAZIONE MACCHINA A STATI (FSM in MariaDB)
    # Eseguiamo la Stored Procedure. Nessun dato viene estratto in Python, calcola tutto SQL.
    execute_query(conn, "CALL EvaluateProactiveState(?, ?, @p_action_state)", (user_id, req.beacon_id), fetch=False)
    
    # Leggiamo il verdetto della macchina a stati
    state_result = execute_query(conn, "SELECT @p_action_state AS state", fetchone=True, dict=True)
    action_state = state_result['state'] if state_result and state_result['state'] else "SILENT_UNKNOWN"
    
    # 4. Routing dell'Intento
    intent = None
    if action_state == "TRIGGER_FITNESS":
        intent = "fitness"
    elif action_state == "TRIGGER_HOBBY":
        intent = "hobby"

    # 5. Esecuzione Proattiva e Rate Limiting
    if intent:
        try:
            # Blocchiamo lo spam: Inseriamo il log per non inviare un'altra notifica qui per la prossima ora
            spam_query = "INSERT INTO sent_notifications (user_id, beacon_id) VALUES (?, ?)"
            execute_query(conn, spam_query, (user_id, req.beacon_id), fetch=False)
            
            # Deleghiamo la generazione del testo e la chiamata di rete al task asincrono
            background_tasks.add_task(send_proactive_notification_task, user_id, intent, req.beacon_id)
            logging.info(f"Task background assegnato per user {user_id} con intento {intent}")
            
        except Exception as db_err:
            logging.error(f"Errore durante l'inserimento in sent_notifications: {db_err}")

    return {
        "log": presence_data,
        "action_state": action_state,
        "intent": intent
    }


@router.put("/{presence_id}/exit", response_model=PresenceLog)
def log_presence_exit(user_id: str, presence_id: str, conn: mariadb.Connection = Depends(db_connection)):
    """
    Chiusura sessione di permanenza e calcolo durata.
    (Rimasto inalterato dal tuo codice originale)
    """
    log_query = "SELECT entry_timestamp, exit_timestamp FROM zone_presence_logs WHERE presence_id = ? AND user_id = ?"
    presence_log = execute_query(conn, log_query, (presence_id, user_id), fetchone=True, dict=True)
    
    if not presence_log:
        raise HTTPException(status_code=404, detail="Presence log not found")
    if presence_log['exit_timestamp'] is not None:
        raise HTTPException(status_code=400, detail="Presence session already closed")

    now = datetime.utcnow()
    entry_time = presence_log['entry_timestamp']
    
    duration = int((now - entry_time).total_seconds() / 60)
    
    update_query = """
        UPDATE zone_presence_logs 
        SET exit_timestamp = ?, duration_minutes = ?
        WHERE presence_id = ?
    """
    execute_query(conn, update_query, (now.strftime('%Y-%m-%d %H:%M:%S'), max(0, duration), presence_id), fetch=False)
    
    select_query = "SELECT * FROM zone_presence_logs WHERE presence_id = ?"
    return execute_query(conn, select_query, (presence_id,), fetchone=True, dict=True)