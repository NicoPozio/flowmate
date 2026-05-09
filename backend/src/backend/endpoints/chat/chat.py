# =============================================================================
# [MODIFIED HCI - 2026-05-08]
# Modifiche apportate:
#   1. COMMENTATO l'endpoint POST /users/{user_id}/chat (chat testuale rimossa)
#   2. COMMENTATO l'endpoint GET  /users/{user_id}/history (idem)
#   3. MANTENUTI gli endpoint /suggestions/{id}/accept e /reject
#   4. [MILESTONE 3] Potenziato /reject con parametro 'reason' (Rifiuto Intelligente)
# =============================================================================

import os
import json
import uuid
import logging
from datetime import date, datetime
import google.generativeai as genai
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.chat.models import ChatRequest, ChatResponse, Option
from pydantic import BaseModel

router = APIRouter(prefix="/users/{user_id}", tags=["Chat & AI Suggestions"])

# Inizializzazione Gemini 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Nuovo modello per il Rifiuto Intelligente (Task 3.5)
class RejectRequest(BaseModel):
    reason: str = "later_30min"  # Valori attesi: 'later_30min', 'today_no', 'dislike'

# =====================================================================
# ★ NEXUS — ENDPOINT ACCETTAZIONE (TENUTO E FONDAMENTALE)
# =====================================================================
@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(user_id: str, suggestion_id: str, conn: mariadb.Connection = Depends(db_connection)):
    """
    Accetta un suggerimento di attivita'. Registra una baseline biometrica.
    """
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

# =====================================================================
# ★ NEXUS — ENDPOINT RIFIUTO INTELLIGENTE (Task 3.5, 3.6, 3.7)
# =====================================================================
@router.post("/suggestions/{suggestion_id}/reject")
def reject_suggestion(user_id: str, suggestion_id: str, request: RejectRequest, conn: mariadb.Connection = Depends(db_connection)):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. Aggiorna lo stato e salva la ragione (se today_no, la FSM lo leggerà)
    execute_query(conn, """
        UPDATE activity_suggestions 
        SET status = 'REJECTED', rejection_reason = ?, rejected_at = ?
        WHERE suggestion_id = ? AND user_id = ?
    """, (request.reason, now_str, suggestion_id, user_id), fetch=False)

    # 2. Logica Rifiuto Intelligente: "dislike" -> Penalizza Hobby (Task 3.6)
    if request.reason == "dislike":
        sugg = execute_query(conn, "SELECT hobby_id FROM activity_suggestions WHERE suggestion_id = ?", (suggestion_id,), fetchone=True, dict=True)
        if sugg:
            hobby_id = sugg['hobby_id']
            # Abbassa preference_level ma non scendere sotto l'1
            execute_query(conn, """
                UPDATE user_hobbies 
                SET preference_level = GREATEST(1, preference_level - 1)
                WHERE user_id = ? AND hobby_id = ?
            """, (user_id, hobby_id), fetch=False)

    return {"status": "success", "message": f"Attivita' rifiutata. Motivo registrato: {request.reason}"}