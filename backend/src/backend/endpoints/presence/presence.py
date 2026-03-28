import uuid
from fastapi import APIRouter, Depends, HTTPException, status
import mariadb
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/users/{user_id}/presence", tags=["Presence Tracking"])

# --- Models ---
class PresenceEntryRequest(BaseModel):
    beacon_id: str

class PresenceResponse(BaseModel):
    presence_id: str
    user_id: str
    beacon_id: str
    entry_timestamp: datetime
    exit_timestamp: Optional[datetime] = None
    duration_minutes: Optional[int] = None

# --- Endpoints ---
@router.post("/entry", response_model=PresenceResponse, status_code=status.HTTP_201_CREATED)
def log_presence_entry(user_id: str, req: PresenceEntryRequest, conn: mariadb.Connection = Depends(db_connection)):
    """
    Apertura sessione di permanenza (ingresso nel raggio BLE).
    """
    # Verifica che il beacon esista
    check_beacon = execute_query(conn, "SELECT beacon_id FROM beacons_catalog WHERE beacon_id = ?", (req.beacon_id,), fetchone=True)
    if not check_beacon:
        raise HTTPException(status_code=400, detail="Invalid beacon_id")

    new_presence_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    insert_query = """
        INSERT INTO zone_presence_logs (presence_id, user_id, beacon_id, entry_timestamp)
        VALUES (?, ?, ?, ?)
    """
    execute_query(conn, insert_query, (new_presence_id, user_id, req.beacon_id, now.strftime('%Y-%m-%d %H:%M:%S')), fetch=False)
    
    select_query = "SELECT * FROM zone_presence_logs WHERE presence_id = ?"
    return execute_query(conn, select_query, (new_presence_id,), fetchone=True, dict=True)


@router.put("/{presence_id}/exit", response_model=PresenceResponse)
def log_presence_exit(user_id: str, presence_id: str, conn: mariadb.Connection = Depends(db_connection)):
    """
    Chiusura sessione di permanenza e calcolo durata.
    """
    # Recupera il log di ingresso per calcolare la durata
    log_query = "SELECT entry_timestamp, exit_timestamp FROM zone_presence_logs WHERE presence_id = ? AND user_id = ?"
    presence_log = execute_query(conn, log_query, (presence_id, user_id), fetchone=True, dict=True)
    
    if not presence_log:
        raise HTTPException(status_code=404, detail="Presence log not found")
    if presence_log['exit_timestamp'] is not None:
        raise HTTPException(status_code=400, detail="Presence session already closed")

    now = datetime.utcnow()
    entry_time = presence_log['entry_timestamp']
    
    # Calcolo della durata in minuti interi
    duration = int((now - entry_time).total_seconds() / 60)
    
    update_query = """
        UPDATE zone_presence_logs 
        SET exit_timestamp = ?, duration_minutes = ?
        WHERE presence_id = ?
    """
    execute_query(conn, update_query, (now.strftime('%Y-%m-%d %H:%M:%S'), max(0, duration), presence_id), fetch=False)
    
    select_query = "SELECT * FROM zone_presence_logs WHERE presence_id = ?"
    return execute_query(conn, select_query, (presence_id,), fetchone=True, dict=True)