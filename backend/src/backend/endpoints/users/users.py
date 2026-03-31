import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from db.mariadb import db_connection, execute_query
from endpoints.users.models import UserCreate, UserResponse
from endpoints.users.models import BaseModel

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



class QuickAuthRequest(BaseModel):
    username: str

class UserResponse(BaseModel):
    user_id: str
    username: str

@router.post("/quick-auth", response_model=UserResponse)
def quick_login_or_register(req: QuickAuthRequest, conn: mariadb.Connection = Depends(db_connection)):
    """
    Cerca l'utente per nome. Se non esiste, lo crea con valori di default.
    """
    # 1. Controlla se l'utente esiste già
    check_query = "SELECT user_id, username FROM users WHERE username = ?"
    existing_user = execute_query(conn, check_query, (req.username,), fetchone=True, dict=True)
    
    if existing_user:
        return existing_user

    # 2. Se è nuovo, lo crea. Inseriamo 70kg e 2000kcal come default per rispettare il NOT NULL
    new_user_id = str(uuid.uuid4())
    insert_query = """
        INSERT INTO users (user_id, username, weight_kg, daily_kcal_goal) 
        VALUES (?, ?, ?, ?)
    """
    execute_query(conn, insert_query, (new_user_id, req.username, 70.0, 2000), fetch=False)
    
    return {"user_id": new_user_id, "username": req.username}