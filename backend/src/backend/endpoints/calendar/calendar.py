# endpoints/calendar/calendar.py
from fastapi import APIRouter, Depends
import mariadb
from datetime import date, timedelta
from pydantic import BaseModel
from typing import List, Optional

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/users/{user_id}/calendar", tags=["Calendar"])

# Modello in uscita
class CalendarItem(BaseModel):
    time: str
    type: str
    title: str
    calories: Optional[int] = None
    duration: str

# Funzione per trasformare i minuti in "1h 30min" o "45min"
def format_duration(minutes: int) -> str:
    if not minutes: return "In corso..."
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0: return f"{hours}h {mins}min"
    elif hours > 0: return f"{hours}h"
    else: return f"{mins}min"

@router.get("/today", response_model=List[CalendarItem])
def get_today_calendar(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    timeline = []

    # 1. Prendi le attività FISICHE completate oggi
    activities_query = """
        SELECT a.completed_at, a.suggested_duration_minutes, a.expected_kcal, h.hobby_name
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        WHERE a.user_id = ? AND a.status = 'COMPLETED' AND DATE(a.completed_at) = ?
    """
    activities = execute_query(conn, activities_query, (user_id, today_str), dict=True)
    if activities:
        for act in activities:
            end_time = act['completed_at']
            duration = act['suggested_duration_minutes'] or 0
            # Calcola l'ora di inizio: Ora di fine - Durata
            start_time = end_time - timedelta(minutes=duration)
            timeline.append({
                "start_time_obj": start_time,
                "time": start_time.strftime("%H:%M"),
                "type": "completed",
                "title": act['hobby_name'],
                "calories": act['expected_kcal'],
                "duration": format_duration(duration)
            })

    # 2. Prendi gli spostamenti nelle STANZE (Beacon) di oggi
    presence_query = """
        SELECT z.entry_timestamp, z.exit_timestamp, z.duration_minutes, b.zone_name
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND DATE(z.entry_timestamp) = ?
    """
    presences = execute_query(conn, presence_query, (user_id, today_str), dict=True)
    if presences:
        for p in presences:
            start_time = p['entry_timestamp']
            duration = p['duration_minutes']
            timeline.append({
                "start_time_obj": start_time,
                "time": start_time.strftime("%H:%M"),
                "type": "presence",
                "title": p['zone_name'],
                "calories": None, # I beacon non hanno calorie!
                "duration": format_duration(duration) if p['exit_timestamp'] else "In corso..."
            })

    # 3. Ordina tutto in ordine cronologico crescente (dal mattino alla sera)
    timeline.sort(key=lambda x: x["start_time_obj"])

    return [CalendarItem(**item) for item in timeline]