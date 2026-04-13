import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.schedule.models import ScheduleCreate, ScheduleResponse

router = APIRouter(prefix="/users/{user_id}/schedule", tags=["Schedule"])

# --- FUNZIONE DI SUPPORTO ---
# Trasforma i "secondi" di MariaDB in un orario leggibile per l'app Android
def format_timedelta(td):
    if isinstance(td, datetime.timedelta):
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return td

@router.post("/", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule_event(user_id: str, event: ScheduleCreate, conn: mariadb.Connection = Depends(db_connection)):
    new_event_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO silent_schedule (event_id, user_id, day_of_week, start_time, end_time, event_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    params = (
        new_event_id, 
        user_id, 
        event.day_of_week, 
        event.start_time.strftime('%H:%M:%S'), 
        event.end_time.strftime('%H:%M:%S'), 
        event.event_type
    )
    execute_query(conn, insert_query, params, fetch=False)
    
    select_query = "SELECT event_id, user_id, day_of_week, start_time, end_time, event_type FROM silent_schedule WHERE event_id = ?"
    result = execute_query(conn, select_query, (new_event_id,), fetchone=True, dict=True)
    
    # TRADUZIONE ORARIO PRIMA DI RISPONDERE
    if result:
        result['start_time'] = format_timedelta(result['start_time'])
        result['end_time'] = format_timedelta(result['end_time'])
        
    return result

@router.get("/", response_model=list[ScheduleResponse])
def get_user_schedule(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    query = "SELECT event_id, user_id, day_of_week, start_time, end_time, event_type FROM silent_schedule WHERE user_id = ?"
    schedule = execute_query(conn, query, (user_id,), dict=True)
    
    # TRADUZIONE ORARIO PER TUTTA LA LISTA
    if schedule:
        for s in schedule:
            s['start_time'] = format_timedelta(s['start_time'])
            s['end_time'] = format_timedelta(s['end_time'])
            
    return schedule if schedule else []

@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule_event(user_id: str, event_id: str, conn: mariadb.Connection = Depends(db_connection)):
    check_query = "SELECT event_id FROM silent_schedule WHERE event_id = ? AND user_id = ?"
    event = execute_query(conn, check_query, (event_id, user_id), fetchone=True)
    
    if not event:
        raise HTTPException(status_code=404, detail="Schedule event not found")
        
    delete_query = "DELETE FROM silent_schedule WHERE event_id = ?"
    execute_query(conn, delete_query, (event_id,), fetch=False)