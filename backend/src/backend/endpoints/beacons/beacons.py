import uuid
from pydantic import BaseModel
from typing import Optional
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
    allow_notifications: bool = True
    zone_icon: str = "Place"
    weekday_from_time: str = "08:00:00"
    weekday_to_time: str = "22:00:00"
    weekend_from_time: str = "09:00:00"
    weekend_to_time: str = "23:00:00"
    associated_hobby_id: Optional[int] = None # ★ NEW M3: Riceve l'hobby dalla UI

@router.post("/")
def register_beacon(req: BeaconCreateRequest, conn: mariadb.Connection = Depends(db_connection)):
    new_id = str(uuid.uuid4())
    # ★ Query aggiornata con associated_hobby_id
    query = """
        INSERT INTO beacons_catalog 
        (beacon_id, user_id, hardware_uuid, major_id, minor_id, zone_name, allow_notifications, 
        zone_icon, weekday_from_time, weekday_to_time, weekend_from_time, weekend_to_time, associated_hobby_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        params = (
            new_id, req.user_id, req.hardware_uuid, req.major_id, req.minor_id, req.zone_name, req.allow_notifications,
            req.zone_icon, req.weekday_from_time, req.weekday_to_time, req.weekend_from_time, req.weekend_to_time,
            req.associated_hobby_id
        )
        execute_query(conn, query, params, fetch=False)
        return {"message": "Beacon saved successfully", "beacon_id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# GET, DELETE e PUT rimangono invariati rispetto al tuo beacons.py precedente...

@router.get("/{user_id}")
def get_user_beacons(user_id: str, conn: mariadb.Connection = Depends(db_connection)):
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
            b['allow_notifications'] = bool(b.get('allow_notifications', False))
            
            # Formattazione campi orario
            for time_field in ['weekday_from_time', 'weekday_to_time', 'weekend_from_time', 'weekend_to_time']:
                if time_field in b and b[time_field] is not None:
                    b[time_field] = str(b[time_field])
            
    return beacons or []

@router.delete("/{beacon_id}")
def delete_beacon(beacon_id: str, conn: mariadb.Connection = Depends(db_connection)):
    execute_query(conn, "DELETE FROM beacons_catalog WHERE beacon_id = ?", (beacon_id,), fetch=False)
    return {"status": "deleted"}

@router.put("/{beacon_id}")
def update_beacon(beacon_id: str, req: BeaconCreateRequest, conn: mariadb.Connection = Depends(db_connection)):
    query = """
        UPDATE beacons_catalog 
        SET zone_name = ?, allow_notifications = ?, zone_icon = ?, 
            weekday_from_time = ?, weekday_to_time = ?, weekend_from_time = ?, weekend_to_time = ?
        WHERE beacon_id = ?
    """
    execute_query(conn, query, (req.zone_name, req.allow_notifications, req.zone_icon, 
                                req.weekday_from_time, req.weekday_to_time, 
                                req.weekend_from_time, req.weekend_to_time, beacon_id), fetch=False)
    return {"status": "updated"}