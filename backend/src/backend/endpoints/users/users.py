import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.users.models import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, conn: mariadb.Connection = Depends(db_connection)):
    check_query = "SELECT user_id FROM users WHERE username = ?"
    existing_user = execute_query(conn, check_query, (user.username,), fetchone=True)
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    new_user_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO users (user_id, username, weight_kg, daily_kcal_goal)
        VALUES (?, ?, ?, ?)
    """
    execute_query(conn, insert_query, (new_user_id, user.username, float(user.weight_kg), user.daily_kcal_goal), fetch=False)
    
    select_query = "SELECT user_id, username, weight_kg, daily_kcal_goal, registration_date FROM users WHERE user_id = ?"
    user_record = execute_query(conn, select_query, (new_user_id,), fetchone=True, dict=True)
    
    if not user_record:
        raise HTTPException(status_code=500, detail="Error retrieving created user")
        
    return user_record

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    query = "SELECT user_id, username, weight_kg, daily_kcal_goal, registration_date FROM users WHERE user_id = ?"
    user_record = execute_query(conn, query, (user_id,), fetchone=True, dict=True)
    
    if not user_record:
        raise HTTPException(status_code=404, detail="User not found")
        
    return user_record