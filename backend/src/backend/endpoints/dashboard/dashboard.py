# endpoints/dashboard/dashboard.py
from fastapi import APIRouter, Depends
import mariadb
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/users/{user_id}/dashboard", tags=["Dashboard"])

class ActivityStatus(BaseModel):
    hobby_name: str
    duration: int
    kcal: int
    status: str

# Esteso con i dati contestuali per M3 (Task 3.4)
class DashboardStatusResponse(BaseModel):
    current_activity: Optional[ActivityStatus] = None
    current_location: Optional[str] = None
    minutes_in_zone: Optional[int] = 0
    kcal_remaining: Optional[int] = 0
    contextual_message: Optional[str] = None

@router.get("/status", response_model=DashboardStatusResponse)
def get_dashboard_status(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    
    # 1. Trova l'attività in sospeso (ORA INCLUDE 'COMPLETED')
    activity_query = """
        SELECT h.hobby_name, a.suggested_duration_minutes as duration, a.expected_kcal as kcal, a.status
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        WHERE a.user_id = ? AND DATE(a.created_at) = ? AND a.status IN ('ACCEPTED', 'PROPOSED', 'COMPLETED')
        ORDER BY FIELD(a.status, 'ACCEPTED', 'PROPOSED', 'COMPLETED'), a.created_at DESC
        LIMIT 1
    """
    act_row = execute_query(conn, activity_query, (user_id, today_str), fetchone=True, dict=True)
    
    # 2. Trova il beacon attivo e calcola i minuti in zona
    beacon_query = """
        SELECT b.zone_name, z.entry_timestamp 
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND z.exit_timestamp IS NULL
        ORDER BY z.entry_timestamp DESC LIMIT 1
    """
    beacon_row = execute_query(conn, beacon_query, (user_id,), fetchone=True, dict=True)
    
    minutes_in_zone = 0
    if beacon_row:
        time_diff = datetime.utcnow() - beacon_row['entry_timestamp']
        minutes_in_zone = max(0, int(time_diff.total_seconds() / 60))

    # 3. Calcola kcal mancanti
    user_data = execute_query(conn, "SELECT daily_kcal_goal FROM users WHERE user_id = ?", (user_id,), fetchone=True, dict=True)
    bio_data = execute_query(conn, "SELECT kcal_burned FROM biometric_logs WHERE user_id = ? AND record_date = ?", (user_id, today_str), fetchone=True, dict=True)
    
    goal = user_data['daily_kcal_goal'] if user_data else 2000
    burned = bio_data['kcal_burned'] if bio_data else 0
    kcal_remaining = max(0, goal - burned)

    # 4. Genera il microcopy contestuale
    context_msg = "Non sei in nessuna zona tracciata."
    if beacon_row:
        context_msg = f"Sei in {beacon_row['zone_name']} da {minutes_in_zone} minuti."

    return {
        "current_activity": act_row,
        "current_location": beacon_row['zone_name'] if beacon_row else None,
        "minutes_in_zone": minutes_in_zone,
        "kcal_remaining": kcal_remaining,
        "contextual_message": context_msg
    }