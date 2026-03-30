import uuid
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
import mariadb
from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/beacons", tags=["Beacons"])

class BeaconCreateRequest(BaseModel):
    user_id: str
    hardware_uuid: str
    major_id: int
    minor_id: int
    zone_name: str

@router.post("/")
def register_beacon(req: BeaconCreateRequest, conn: mariadb.Connection = Depends(db_connection)):
    new_id = str(uuid.uuid4())
    query = """
        INSERT INTO beacons_catalog (beacon_id, user_id, hardware_uuid, major_id, minor_id, zone_name)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    try:
        execute_query(conn, query, (new_id, req.user_id, req.hardware_uuid, req.major_id, req.minor_id, req.zone_name), fetch=False)
        return {"message": "Beacon saved successfully", "beacon_id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/{user_id}")
def get_user_beacons(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
    # Query DEFINITIVA: Se l'uscita è NULL, è attivo (1). Altrimenti è inattivo (0).
    query = """
        SELECT 
            b.*,
            (SELECT CASE WHEN exit_timestamp IS NULL THEN 1 ELSE 0 END 
             FROM zone_presence_logs z 
             WHERE z.beacon_id = b.beacon_id AND z.user_id = ?
             ORDER BY entry_timestamp DESC LIMIT 1) as is_active,
            (SELECT entry_timestamp 
             FROM zone_presence_logs z 
             WHERE z.beacon_id = b.beacon_id AND z.user_id = ?
             ORDER BY entry_timestamp DESC LIMIT 1) as last_seen
        FROM beacons_catalog b 
        WHERE b.user_id = ?
    """
    beacons = execute_query(conn, query, (user_id, user_id, user_id), fetchone=False, dict=True)
    
    if beacons:
        for b in beacons:
            b['is_active'] = bool(b['is_active']) if b['is_active'] is not None else False
            b['last_seen'] = str(b['last_seen']).split(".")[0] if b['last_seen'] else "Mai visto"
            
    return beacons or []