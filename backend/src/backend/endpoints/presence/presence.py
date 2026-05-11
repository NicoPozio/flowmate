# src/backend/endpoints/presence/presence.py

import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
import mariadb
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from db.mariadb import db_connection, execute_query
from notifications.push_service import send_proactive_notification_task

router = APIRouter(prefix="/users/{user_id}/presence", tags=["Presence Tracking"])

class PresenceEntryRequest(BaseModel):
    beacon_id: str

class PresenceExitRequest(BaseModel):
    exit_timestamp_ms: int

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

@router.post("/entry", response_model=PresenceEntryResponse, status_code=status.HTTP_201_CREATED)
def log_presence_entry(
    user_id: str, 
    req: PresenceEntryRequest, 
    background_tasks: BackgroundTasks,
    conn: mariadb.Connection = Depends(db_connection)
):
    cleanup_query = """
        UPDATE zone_presence_logs 
        SET exit_timestamp = UTC_TIMESTAMP(), 
            duration_minutes = TIMESTAMPDIFF(MINUTE, entry_timestamp, UTC_TIMESTAMP())
        WHERE user_id = ? AND exit_timestamp IS NULL
    """
    execute_query(conn, cleanup_query, (user_id,), fetch=False)

    check_beacon = execute_query(conn, "SELECT beacon_id, associated_hobby_id, zone_name FROM beacons_catalog WHERE beacon_id = ?", (req.beacon_id,), fetchone=True, dict=True)
    if not check_beacon:
        raise HTTPException(status_code=400, detail="Invalid beacon_id")

    new_presence_id = str(uuid.uuid4())
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    insert_query = """
        INSERT INTO zone_presence_logs (presence_id, user_id, beacon_id, entry_timestamp)
        VALUES (?, ?, ?, ?)
    """
    execute_query(conn, insert_query, (new_presence_id, user_id, req.beacon_id, now_str), fetch=False)
    presence_data = execute_query(conn, "SELECT * FROM zone_presence_logs WHERE presence_id = ?", (new_presence_id,), fetchone=True, dict=True)

    execute_query(conn, "CALL EvaluateProactiveState(?, ?, @p_action_state)", (user_id, req.beacon_id), fetch=False)
    state_result = execute_query(conn, "SELECT @p_action_state AS state", fetchone=True, dict=True)
    action_state = state_result['state'] if state_result and state_result['state'] else "SILENT_UNKNOWN"
    
    intent = "fitness" if action_state == "TRIGGER_FITNESS" else "hobby" if action_state == "TRIGGER_HOBBY" else None

    if intent:
        try:
            hobby_id = check_beacon['associated_hobby_id']
            hobby_name = "un'attività"

            if hobby_id:
                user_pref = execute_query(conn, """
                    SELECT preference_level 
                    FROM user_hobbies 
                    WHERE user_id = ? AND hobby_id = ?
                """, (user_id, hobby_id), fetchone=True, dict=True)
                
                if user_pref and user_pref['preference_level'] <= 2:
                    logging.info(f"Hobby ambientale ignorato per punteggio basso ({user_pref['preference_level']}). Attivazione Fallback.")
                    hobby_id = None

            if not hobby_id:
                fav_hobby = execute_query(conn, """
                    SELECT h.hobby_id, h.hobby_name 
                    FROM user_hobbies uh
                    JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
                    WHERE uh.user_id = ? 
                    ORDER BY uh.preference_level DESC LIMIT 1
                """, (user_id,), fetchone=True, dict=True)
                if fav_hobby:
                    hobby_id = fav_hobby['hobby_id']
                    hobby_name = fav_hobby['hobby_name']
                else:
                    hobby_id = 1 
            else:
                h_info = execute_query(conn, "SELECT hobby_name FROM hobbies_catalog WHERE hobby_id = ?", (hobby_id,), fetchone=True, dict=True)
                if h_info: hobby_name = h_info['hobby_name']

            suggestion_id = str(uuid.uuid4())
            execute_query(conn, """
                UPDATE activity_suggestions 
                SET status = 'REJECTED' 
                WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = CURRENT_DATE()
            """, (user_id,), fetch=False)

            execute_query(conn, """
                INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
                VALUES (?, ?, ?, ?, ?, 'PROPOSED')
            """, (suggestion_id, user_id, hobby_id, 30, 150), fetch=False)

            execute_query(conn, "INSERT INTO sent_notifications (user_id, beacon_id) VALUES (?, ?)", (user_id, req.beacon_id), fetch=False)
            
            minutes = 0
            
            # =====================================================================
            # CHIAMATA NOTIFICA PUSH: Questo invia la notifica del Beacon via Firebase
            # =====================================================================
            background_tasks.add_task(
                send_proactive_notification_task, 
                user_id, 
                intent, 
                req.beacon_id, 
                suggestion_id, 
                hobby_name,
                check_beacon['zone_name'],
                minutes
            )
            
        except Exception as e:
            logging.warning(f"Errore generazione suggerimento proattivo: {e}")

    return {"log": presence_data, "action_state": action_state, "intent": intent}

@router.put("/{presence_id}/exit", response_model=PresenceLog)
def log_presence_exit(user_id: str, presence_id: str, req: PresenceExitRequest, conn: mariadb.Connection = Depends(db_connection)):
    log_query = "SELECT entry_timestamp, exit_timestamp FROM zone_presence_logs WHERE presence_id = ? AND user_id = ?"
    presence_log = execute_query(conn, log_query, (presence_id, user_id), fetchone=True, dict=True)
    
    if not presence_log or presence_log['exit_timestamp']:
        raise HTTPException(status_code=400, detail="Session not found or already closed")

    real_exit_time = datetime.utcfromtimestamp(req.exit_timestamp_ms / 1000.0)
    duration = max(0, int((real_exit_time - presence_log['entry_timestamp']).total_seconds() / 60))
    
    execute_query(conn, "UPDATE zone_presence_logs SET exit_timestamp = ?, duration_minutes = ? WHERE presence_id = ?", 
                  (real_exit_time.strftime('%Y-%m-%d %H:%M:%S'), duration, presence_id), fetch=False)
    
    return execute_query(conn, "SELECT * FROM zone_presence_logs WHERE presence_id = ?", (presence_id,), fetchone=True, dict=True)