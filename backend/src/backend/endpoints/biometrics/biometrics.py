import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.biometrics.models import BiometricLogCreate, BiometricLogResponse

router = APIRouter(prefix="/users/{user_id}/biometrics", tags=["Biometrics"])

@router.post("/", response_model=BiometricLogResponse, status_code=status.HTTP_201_CREATED)
def sync_biometrics(user_id: str, log_data: BiometricLogCreate, conn: mariadb.Connection = Depends(db_connection)):
    new_log_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO biometric_logs (log_id, user_id, log_timestamp, steps_recorded, kcal_burned)
        VALUES (?, ?, ?, ?, ?)
    """
    params = (new_log_id, user_id, log_data.log_timestamp.strftime('%Y-%m-%d %H:%M:%S'), log_data.steps_recorded, log_data.kcal_burned)
    execute_query(conn, insert_query, params, fetch=False)
    
    select_query = "SELECT log_id, user_id, log_timestamp, steps_recorded, kcal_burned FROM biometric_logs WHERE log_id = ?"
    return execute_query(conn, select_query, (new_log_id,), fetchone=True, dict=True)

@router.get("/today", response_model=BiometricLogResponse)
def get_latest_biometrics_today(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    query = """
        SELECT log_id, user_id, log_timestamp, steps_recorded, kcal_burned 
        FROM biometric_logs 
        WHERE user_id = ? AND DATE(log_timestamp) = CURDATE() 
        ORDER BY log_timestamp DESC 
        LIMIT 1
    """
    latest_log = execute_query(conn, query, (user_id,), fetchone=True, dict=True)
    
    if not latest_log:
        raise HTTPException(status_code=404, detail="No biometrics logged today")
    return latest_log