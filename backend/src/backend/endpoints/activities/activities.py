import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.activities.models import ActivityCreate, ActivityResponse

router = APIRouter(prefix="/users/{user_id}/activities", tags=["Activities"])

@router.post("/", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
def log_completed_activity(user_id: str, activity_data: ActivityCreate, conn: mariadb.Connection = Depends(db_connection)):
    check_hobby = execute_query(conn, "SELECT hobby_id FROM hobbies_catalog WHERE hobby_id = ?", (activity_data.hobby_id,), fetchone=True)
    if not check_hobby:
        raise HTTPException(status_code=400, detail="Invalid hobby_id")

    new_activity_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO completed_activities (activity_id, user_id, hobby_id, duration_minutes, completion_timestamp)
        VALUES (?, ?, ?, ?, ?)
    """
    params = (new_activity_id, user_id, activity_data.hobby_id, activity_data.duration_minutes, activity_data.completion_timestamp.strftime('%Y-%m-%d %H:%M:%S'))
    execute_query(conn, insert_query, params, fetch=False)
    
    select_query = """
        SELECT activity_id, user_id, hobby_id, duration_minutes, completion_timestamp 
        FROM completed_activities 
        WHERE activity_id = ?
    """
    return execute_query(conn, select_query, (new_activity_id,), fetchone=True, dict=True)