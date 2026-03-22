import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.schedule.models import ScheduleCreate, ScheduleResponse

router = APIRouter(prefix="/users/{user_id}/schedule", tags=["Schedule"])

@router.post("/", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
def create_schedule_event(user_id: str, event: ScheduleCreate, conn: mariadb.Connection = Depends(db_connection)):
    new_event_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO silent_schedule (event_id, user_id, day_of_week, start_time, end_time, event_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    params = (new_event_id, user_id, event.day_of_week, event.start_time.strftime('%H:%M:%S'), event.end_time.strftime('%H:%M:%S'), event.event_type)
    execute_query(conn, insert_query, params, fetch=False)
    
    select_query = "SELECT event_id, user_id, day_of_week, start_time, end_time, event_type FROM silent_schedule WHERE event_id = ?"
    return execute_query(conn, select_query, (new_event_id,), fetchone=True, dict=True)

@router.get("/", response_model=list[ScheduleResponse])
def get_user_schedule(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    query = "SELECT event_id, user_id, day_of_week, start_time, end_time, event_type FROM silent_schedule WHERE user_id = ?"
    schedule = execute_query(conn, query, (user_id,), dict=True)
    return schedule if schedule else []

@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule_event(user_id: str, event_id: str, conn: mariadb.Connection = Depends(db_connection)):
    check_query = "SELECT event_id FROM silent_schedule WHERE event_id = ? AND user_id = ?"
    event = execute_query(conn, check_query, (event_id, user_id), fetchone=True)
    
    if not event:
        raise HTTPException(status_code=404, detail="Schedule event not found")
        
    delete_query = "DELETE FROM silent_schedule WHERE event_id = ?"
    execute_query(conn, delete_query, (event_id,), fetch=False)