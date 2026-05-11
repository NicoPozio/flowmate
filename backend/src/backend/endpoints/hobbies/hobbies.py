from fastapi import APIRouter, Depends, HTTPException, status
import mariadb

from db.mariadb import db_connection, execute_query
from endpoints.hobbies.models import HobbyResponse, UserHobbyCreate, UserHobbyResponse

router = APIRouter(tags=["Hobbies"])

@router.get("/hobbies/", response_model=list[HobbyResponse])
def get_hobbies_catalog(conn: mariadb.Connection = Depends(db_connection)):
    query = "SELECT hobby_id, hobby_name, met_value FROM hobbies_catalog"
    catalog = execute_query(conn, query, dict=True)
    return catalog if catalog else []

@router.post("/users/{user_id}/hobbies", response_model=list[UserHobbyResponse], status_code=status.HTTP_201_CREATED)
def set_user_hobbies(user_id: str, hobbies: list[UserHobbyCreate], conn: mariadb.Connection = Depends(db_connection)):
    check_user = execute_query(conn, "SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetchone=True)
    if not check_user:
        raise HTTPException(status_code=404, detail="User not found")

    delete_query = "DELETE FROM user_hobbies WHERE user_id = ?"
    execute_query(conn, delete_query, (user_id,), fetch=False)
    
    insert_query = "INSERT INTO user_hobbies (user_id, hobby_id, preference_level) VALUES (?, ?, ?)"
    for hobby in hobbies:
        execute_query(conn, insert_query, (user_id, hobby.hobby_id, hobby.preference_level), fetch=False)
    
    select_query = "SELECT user_id, hobby_id, preference_level FROM user_hobbies WHERE user_id = ?"
    return execute_query(conn, select_query, (user_id,), dict=True)

@router.get("/users/{user_id}/hobbies/favorites", response_model=list[HobbyResponse])
def get_favorite_hobbies(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    query = """
        SELECT hc.hobby_id, hc.hobby_name, hc.met_value 
        FROM hobbies_catalog hc
        JOIN user_hobbies uh ON hc.hobby_id = uh.hobby_id
        WHERE uh.user_id = ? AND uh.preference_level > 2
        ORDER BY uh.preference_level DESC
    """
    catalog = execute_query(conn, query, (user_id,), dict=True)
    return catalog if catalog else []