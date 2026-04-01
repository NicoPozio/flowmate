import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.users.models import UserCreate, UserResponse
from datetime import datetime
router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/check/{username}", response_model=UserResponse)
def check_user_exists(username: str, conn: mariadb.Connection = Depends(db_connection)):
    # 1. Cerchiamo l'utente
    query = "SELECT user_id, username, weight_kg, daily_kcal_goal, registration_date FROM users WHERE username = ?"
    user_record = execute_query(conn, query, (username,), fetchone=True, dict=True)
    
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
        
    # 2. Controlliamo se ha hobby associati
    count_query = "SELECT COUNT(*) as count FROM user_hobbies WHERE user_id = ?"
    result = execute_query(conn, count_query, (user_record['user_id'],), fetchone=True, dict=True)
    
    user_record['has_hobbies'] = result['count'] > 0
    return user_record

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, conn: mariadb.Connection = Depends(db_connection)):
    new_user_id = str(uuid.uuid4())
    insert_query = "INSERT INTO users (user_id, username, weight_kg, daily_kcal_goal) VALUES (?, ?, ?, ?)"
    execute_query(conn, insert_query, (new_user_id, user.username, float(user.weight_kg), user.daily_kcal_goal), fetch=False)
    
    return {
        "user_id": new_user_id,
        "username": user.username,
        "weight_kg": user.weight_kg,
        "daily_kcal_goal": user.daily_kcal_goal,
        "registration_date": datetime.now(),
        "has_hobbies": False # Un nuovo utente non ha hobby
    }