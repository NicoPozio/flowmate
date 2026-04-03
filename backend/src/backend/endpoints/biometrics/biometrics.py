import uuid
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.biometrics.models import BiometricLogCreate, BiometricLogResponse

router = APIRouter(prefix="/users/{user_id}/biometrics", tags=["Biometrics"])

@router.post("/", response_model=BiometricLogResponse, status_code=status.HTTP_201_CREATED)
def sync_biometrics(user_id: str, log_data: BiometricLogCreate, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    
    # 1. LOGICA UPSERT: Se esiste già una riga per oggi, la aggiorniamo. Se no, la creiamo.
    existing_log = execute_query(conn, "SELECT record_date FROM biometric_logs WHERE user_id = ? AND record_date = ?", (user_id, today_str), fetchone=True)
    
    if existing_log:
        execute_query(conn, """
            UPDATE biometric_logs 
            SET steps_recorded = ?, active_minutes = ?, kcal_burned = ?
            WHERE user_id = ? AND record_date = ?
        """, (log_data.steps_recorded, log_data.active_minutes, log_data.kcal_burned, user_id, today_str), fetch=False)
    else:
        execute_query(conn, """
            INSERT INTO biometric_logs (user_id, record_date, steps_recorded, active_minutes, kcal_burned)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, today_str, log_data.steps_recorded, log_data.active_minutes, log_data.kcal_burned), fetch=False)

    # =========================================================================
    # 2. L'ARBITRO: VERIFICA COMPLETAMENTO ATTIVITÀ "ACCEPTED"
    # =========================================================================
    
    # Trova tutte le sfide accettate che non sono ancora state completate
    pending_challenges = execute_query(conn, """
        SELECT suggestion_id, baseline_active_minutes, suggested_duration_minutes 
        FROM activity_suggestions 
        WHERE user_id = ? AND status = 'ACCEPTED'
    """, (user_id,), dict=True)

    if pending_challenges:
        for challenge in pending_challenges:
            # Calcolo Matematico: L'obiettivo era la Baseline + i minuti suggeriti dall'AI
            target_minutes = challenge['baseline_active_minutes'] + challenge['suggested_duration_minutes']
            
            # Se i minuti attuali di Health Connect (log_data.active_minutes) hanno superato l'obiettivo...
            if log_data.active_minutes >= target_minutes:
                # VITTORIA! Aggiorna in COMPLETED e metti l'ora attuale
                execute_query(conn, """
                    UPDATE activity_suggestions 
                    SET status = 'COMPLETED', completed_at = ?
                    WHERE suggestion_id = ?
                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), challenge['suggestion_id']), fetch=False)

    # =========================================================================
    
    # 3. Ritorna i dati aggiornati
    select_query = "SELECT user_id, record_date, steps_recorded, active_minutes, kcal_burned FROM biometric_logs WHERE user_id = ? AND record_date = ?"
    return execute_query(conn, select_query, (user_id, today_str), fetchone=True, dict=True)

@router.get("/today", response_model=BiometricLogResponse)
def get_latest_biometrics_today(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    query = """
        SELECT user_id, record_date, steps_recorded, active_minutes, kcal_burned 
        FROM biometric_logs 
        WHERE user_id = ? AND record_date = ? 
    """
    latest_log = execute_query(conn, query, (user_id, today_str), fetchone=True, dict=True)
    
    if not latest_log:
        raise HTTPException(status_code=404, detail="No biometrics logged today")
    return latest_log