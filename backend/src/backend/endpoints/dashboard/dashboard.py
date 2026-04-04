# endpoints/dashboard/dashboard.py
from fastapi import APIRouter, Depends
import mariadb
from datetime import date
from pydantic import BaseModel
from typing import Optional

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/users/{user_id}/dashboard", tags=["Dashboard"])

class ActivityStatus(BaseModel):
    hobby_name: str
    duration: int
    kcal: int
    status: str

class DashboardStatusResponse(BaseModel):
    current_activity: Optional[ActivityStatus] = None
    current_location: Optional[str] = None

@router.get("/status", response_model=DashboardStatusResponse)
def get_dashboard_status(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    
    # 1. Trova l'attività in sospeso (priorità ad ACCEPTED, poi PROPOSED)
    activity_query = """
        SELECT h.hobby_name, a.suggested_duration_minutes as duration, a.expected_kcal as kcal, a.status
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        WHERE a.user_id = ? AND DATE(a.created_at) = ? AND a.status IN ('ACCEPTED', 'PROPOSED')
        ORDER BY FIELD(a.status, 'ACCEPTED', 'PROPOSED'), a.created_at DESC
        LIMIT 1
    """
    act_row = execute_query(conn, activity_query, (user_id, today_str), fetchone=True, dict=True)
    
    # 2. Trova il beacon attivo (quello senza exit_timestamp)
    beacon_query = """
        SELECT b.zone_name 
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND z.exit_timestamp IS NULL
        ORDER BY z.entry_timestamp DESC LIMIT 1
    """
    beacon_row = execute_query(conn, beacon_query, (user_id,), fetchone=True, dict=True)
    
    return {
        "current_activity": act_row,
        "current_location": beacon_row['zone_name'] if beacon_row else None
    }