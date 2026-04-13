# endpoints/calendar/calendar.py
from fastapi import APIRouter, Depends
import mariadb
from datetime import date
from pydantic import BaseModel
from typing import List, Optional

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/users/{user_id}/calendar", tags=["Calendar"])

class CalendarItem(BaseModel):
    time: str
    type: str
    title: str
    calories: Optional[int] = None
    duration: str

def format_duration(minutes: Optional[int]) -> str:
    if minutes is None: 
        return "In corso..."
    if minutes == 0:
        return "< 1min"
        
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0 and mins > 0: return f"{hours}h {mins}min"
    elif hours > 0: return f"{hours}h"
    else: return f"{mins}min"

@router.get("/today", response_model=List[CalendarItem])
def get_today_calendar(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    today_str = date.today().isoformat()
    timeline = []

    # 1. Recupero attività
    activities_query = """
        SELECT a.completed_at, a.suggested_duration_minutes, h.hobby_name, h.met_value, u.weight_kg
        FROM activity_suggestions a
        JOIN hobbies_catalog h ON a.hobby_id = h.hobby_id
        JOIN users u ON a.user_id = u.user_id
        WHERE a.user_id = ? AND a.status = 'COMPLETED' AND DATE(a.completed_at) = ?
    """
    activities = execute_query(conn, activities_query, (user_id, today_str), dict=True)
    
    if activities:
        for act in activities:
            end_time = act['completed_at'] 
            duration = act['suggested_duration_minutes'] or 0
            met = float(act['met_value'])
            peso = float(act['weight_kg'])
            
            timeline.append({
                "time_obj": end_time,
                "time": end_time.strftime("%Y-%m-%d %H:%M:%S"), # Fix ora legale
                "type": "completed",
                "title": act['hobby_name'],
                "calories": int(met * peso * (duration / 60.0)),
                "duration": format_duration(duration)
            })

    # 2. Recupero presenze Beacon (ANTI-RIMBALZO 3 MINUTI)
    presence_query = """
        SELECT z.entry_timestamp, z.exit_timestamp, z.duration_minutes, b.zone_name
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND DATE(z.entry_timestamp) = ?
        ORDER BY z.entry_timestamp ASC
    """
    raw_presences = execute_query(conn, presence_query, (user_id, today_str), dict=True)
    
    merged_presences = []
    if raw_presences:
        for p in raw_presences:
            if not merged_presences:
                merged_presences.append(p)
                continue
                
            prev = merged_presences[-1]
            is_same_zone = prev['zone_name'] == p['zone_name']
            
            gap_minutes = 0
            if prev['exit_timestamp']:
                gap_minutes = (p['entry_timestamp'] - prev['exit_timestamp']).total_seconds() / 60
            
            # SOGLIA CALCOLATA: 3 minuti
            if is_same_zone and (prev['exit_timestamp'] is None or gap_minutes <= 3):
                prev['exit_timestamp'] = p['exit_timestamp'] 
                if prev['exit_timestamp']:
                    prev['duration_minutes'] = int((prev['exit_timestamp'] - prev['entry_timestamp']).total_seconds() / 60)
                else:
                    prev['duration_minutes'] = None
            else:
                merged_presences.append(p)

    if merged_presences:
        for p in merged_presences:
            start_time = p['entry_timestamp']
            timeline.append({
                "time_obj": start_time,
                "time": start_time.strftime("%Y-%m-%d %H:%M:%S"), # Fix ora legale
                "type": "presence",
                "title": p['zone_name'],
                "calories": None,
                "duration": format_duration(p['duration_minutes']) if p['exit_timestamp'] else "In corso..."
            })

    # 3. Ordina e pulisci
    timeline.sort(key=lambda x: x["time_obj"])
    for item in timeline:
        del item["time_obj"]

    return timeline