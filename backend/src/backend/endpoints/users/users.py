import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from datetime import datetime

# IMPORTIAMO TUTTI I MODELLI DA MODELS.PY
from endpoints.users.models import UserCreate, UserResponse, DailyHealthCreate 

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/check/{username}", response_model=UserResponse)
def check_user_exists(username: str, conn: mariadb.Connection = Depends(db_connection)):
    # 1. Cerchiamo l'utente
    # Aggiunto daily_steps_goal nella SELECT
    query = "SELECT user_id, username, weight_kg, daily_kcal_goal, daily_steps_goal, registration_date FROM users WHERE username = ?"
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
    # Aggiunto daily_steps_goal nella INSERT
    insert_query = "INSERT INTO users (user_id, username, weight_kg, daily_kcal_goal, daily_steps_goal) VALUES (?, ?, ?, ?, ?)"
    execute_query(conn, insert_query, (new_user_id, user.username, float(user.weight_kg), user.daily_kcal_goal, user.daily_steps_goal), fetch=False)
    
    return {
        "user_id": new_user_id,
        "username": user.username,
        "weight_kg": user.weight_kg,
        "daily_kcal_goal": user.daily_kcal_goal,
        "daily_steps_goal": user.daily_steps_goal,
        "registration_date": datetime.now(),
        "has_hobbies": False
    }

@router.post("/{user_id}/health/daily", status_code=status.HTTP_200_OK)
def save_daily_health(user_id: str, health_data: DailyHealthCreate, conn: mariadb.Connection = Depends(db_connection)):
    query = """
        INSERT INTO biometric_logs (user_id, record_date, steps_recorded, active_minutes, kcal_burned)
        VALUES (?, ?, ?, ?, ?)
        ON DUPLICATE KEY UPDATE 
        steps_recorded = VALUES(steps_recorded), 
        active_minutes = VALUES(active_minutes), 
        kcal_burned = VALUES(kcal_burned)
    """
    
    execute_query(conn, query, (
        user_id, 
        health_data.date, 
        health_data.steps, 
        health_data.active_minutes, 
        health_data.calories_burned
    ), fetch=False)
    
    return {"status": "success", "message": "Biometric logs updated"}