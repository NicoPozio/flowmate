from fastapi import APIRouter, Depends
import mariadb
from pydantic import BaseModel
from typing import Optional, List

from db.mariadb import db_connection, execute_query

router = APIRouter(prefix="/beacons", tags=["Beacons"])

# --- Models ---
class BeaconResponse(BaseModel):
    beacon_id: str
    hardware_uuid: str
    major_id: int
    minor_id: int
    zone_name: str
    associated_hobby_id: Optional[int] = None

# --- Endpoint ---
@router.get("/", response_model=List[BeaconResponse])
def get_beacons_catalog(conn: mariadb.Connection = Depends(db_connection)):
    """
    Download del catasto hardware (eseguito dall'app all'avvio).
    """
    query = """
        SELECT beacon_id, hardware_uuid, major_id, minor_id, zone_name, associated_hobby_id 
        FROM beacons_catalog
    """
    beacons = execute_query(conn, query, dict=True)
    return beacons if beacons else []