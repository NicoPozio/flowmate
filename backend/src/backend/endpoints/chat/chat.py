# =============================================================================
# [MODIFIED HCI - 2026-05-09]
# Modifiche apportate:
#   1. MANTENUTI gli endpoint /suggestions/{id}/accept e /reject
#   2. [UPGRADE M4] Reroll immediato anti-loop!
#   3. [HOTFIX 500] Riscritta query con NOT EXISTS per evitare crash MariaDB Connector.
# =============================================================================

import os
import json
import uuid
import logging
from datetime import date, datetime
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.chat.models import ChatRequest, ChatResponse, Option
from pydantic import BaseModel

from notifications.push_service import send_shake_notification_task, send_simple_notification

router = APIRouter(prefix="/users/{user_id}", tags=["Chat & AI Suggestions"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

class RejectRequest(BaseModel):
    reason: str = "later_30min"  

@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(user_id: str, suggestion_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    
    current_logs = execute_query(conn, """
        SELECT SUM(active_minutes) as current_active 
        FROM biometric_logs 
        WHERE user_id = ? AND record_date = ?
    """, (user_id, today_str), fetchone=True, dict=True)
    
    baseline_minutes = current_logs['current_active'] if current_logs and current_logs['current_active'] is not None else 0

    execute_query(conn, """
        UPDATE activity_suggestions 
        SET status = 'ACCEPTED', baseline_active_minutes = ?
        WHERE suggestion_id = ? AND user_id = ?
    """, (baseline_minutes, suggestion_id, user_id), fetch=False)
    
    return {"status": "success", "message": "Attivita' accettata, snapshot registrato."}

@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(user_id: str, suggestion_id: str, request: RejectRequest, background_tasks: BackgroundTasks, conn: mariadb.Connection = Depends(db_connection)):
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        sugg = execute_query(conn, "SELECT hobby_id FROM activity_suggestions WHERE suggestion_id = ?", (suggestion_id,), fetchone=True, dict=True)
        rejected_hobby_id = sugg['hobby_id'] if sugg else 0

        execute_query(conn, """
            UPDATE activity_suggestions 
            SET status = 'REJECTED', rejection_reason = ?, rejected_at = ?
            WHERE suggestion_id = ? AND user_id = ?
        """, (request.reason, now_str, suggestion_id, user_id), fetch=False)

        if request.reason == "dislike":
            execute_query(conn, """
                UPDATE user_hobbies 
                SET preference_level = GREATEST(1, preference_level - 1)
                WHERE user_id = ? AND hobby_id = ?
            """, (user_id, rejected_hobby_id), fetch=False)

        # =========================================================================
        # FIX 500: Reroll immediato usando la logica NOT EXISTS (Anti-Crash)
        # =========================================================================
        if request.reason == "change_activity":
            new_hobby = execute_query(conn, """
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

            if new_hobby:
                new_suggestion_id = str(uuid.uuid4())
                execute_query(conn, """
                    INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
                    VALUES (?, ?, ?, 30, 150, 'PROPOSED')
                """, (new_suggestion_id, user_id, new_hobby['hobby_id']), fetch=False)

                background_tasks.add_task(
                    send_shake_notification_task,
                    user_id=user_id,
                    suggestion_id=new_suggestion_id,
                    hobby_name=new_hobby['hobby_name'],
                    zone_name=None,
                    minutes_in_zone=0
                )
            else:
                background_tasks.add_task(
                    send_simple_notification, 
                    user_id, 
                    "Finito le idee! 😅", 
                    "Hai scartato tutte le tue attività preferite per oggi. Goditi il meritato riposo, non ti disturberò più!"
                )

        return {"status": "success", "message": f"Attivita' rifiutata. Motivo: {request.reason}"}
        
    except Exception as e:
        logging.error(f"Errore 500 in reject_suggestion: {e}")
        raise HTTPException(status_code=500, detail="Errore interno durante il rifiuto dell'attività")