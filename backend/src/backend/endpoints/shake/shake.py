from fastapi import APIRouter, BackgroundTasks, Path, Depends, HTTPException
import uuid
import logging
import mariadb
from datetime import date, datetime
from db.mariadb import db_connection, execute_query

from notifications.push_service import send_shake_notification_task, send_simple_notification

router = APIRouter(tags=["Shake"])

@router.post("/users/{user_id}/shake")
async def trigger_shake_action(
    background_tasks: BackgroundTasks,
    user_id: str = Path(...),
    conn: mariadb.Connection = Depends(db_connection)
):
    today_str = date.today().isoformat()

    # 1. Recupero Dati Zona
    presence = execute_query(conn, """
        SELECT z.beacon_id, b.zone_name, b.associated_hobby_id, z.entry_timestamp 
        FROM zone_presence_logs z
        JOIN beacons_catalog b ON z.beacon_id = b.beacon_id
        WHERE z.user_id = ? AND z.exit_timestamp IS NULL
        ORDER BY z.entry_timestamp DESC LIMIT 1
    """, (user_id,), fetchone=True, dict=True)

    beacon_id_val = presence['beacon_id'] if presence else None

    # =========================================================================
    # 2. CONTROLLO ATTIVITÀ IN CORSO
    # =========================================================================
    existing_activity = execute_query(conn, """
        SELECT status FROM activity_suggestions 
        WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = ?
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, today_str), fetchone=True, dict=True)

    if existing_activity:
        status = existing_activity['status']
        title = "Promemoria 📌"
        body = "Guarda che devi finire ancora la tua attività!" if status == 'ACCEPTED' else "Hai già una proposta in sospeso, accettala o rifiutala!"
        background_tasks.add_task(send_simple_notification, user_id, title, body)
        return {"status": "success", "message": "Reminder sent."}

    # =========================================================================
    # 3. IL CANCELLO DI CONTROLLO (FSM)
    # =========================================================================
    try:
        execute_query(conn, "CALL EvaluateProactiveState(?, ?, @out_state)", (user_id, beacon_id_val), fetch=False)
        fsm_res = execute_query(conn, "SELECT @out_state as state", fetchone=True, dict=True)
        fsm_state = fsm_res['state'] if fsm_res and fsm_res['state'] else "TRIGGER_FITNESS"
    except Exception as e:
        logging.error(f"Errore FSM: {e}")
        fsm_state = "TRIGGER_FITNESS"

    if fsm_state != "TRIGGER_FITNESS":
        logging.info(f"Shake neutralizzato. La FSM ha risposto: {fsm_state}")
        
        title = "Pausa attiva 🛑"
        if fsm_state == 'SILENT_COOLDOWN':
            body = "Hai rifiutato un'attività da poco. Prenditi una pausa, ci riproviamo tra mezz'ora!"
        elif fsm_state == 'SILENT_USER_OPTED_OUT':
            body = "Hai impostato lo stop per oggi. Goditi il relax, non ti disturbo!"
        elif fsm_state == 'SILENT_BUSY_SCHEDULE':
            body = "Sei nel tuo orario di non disturbo. Torna più tardi!"
        elif fsm_state == 'SILENT_ZONE_DISABLED':
            body = "Le notifiche sono disabilitate per questa stanza."
        else:
            body = "Al momento non posso suggerirti nulla. Riposati!"
            
        background_tasks.add_task(send_simple_notification, user_id, title, body)
        return {"status": "blocked", "message": f"Azione bloccata dal sistema: {fsm_state}"}

    # =========================================================================
    # 4. LOGICA CONTESTUALE M3 (Anti-Loop su Beacon)
    # =========================================================================
    zone_name = None
    minutes_in_zone = 0
    hobby_id = None
    hobby_name = "un'attività"

    if presence:
        zone_name = presence['zone_name']
        time_diff = datetime.utcnow() - presence['entry_timestamp']
        minutes_in_zone = max(0, int(time_diff.total_seconds() / 60))
        
        if presence['associated_hobby_id']:
            assoc_hobby = presence['associated_hobby_id']
            user_pref = execute_query(conn, """
                SELECT preference_level 
                FROM user_hobbies 
                WHERE user_id = ? AND hobby_id = ?
            """, (user_id, assoc_hobby), fetchone=True, dict=True)
            
            if not user_pref or user_pref['preference_level'] > 2:
                # Controlliamo che l'hobby della stanza NON sia già stato scartato oggi
                already_rejected = execute_query(conn, """
                    SELECT 1 FROM activity_suggestions 
                    WHERE user_id = ? AND hobby_id = ? AND status = 'REJECTED' AND DATE(created_at) = CURDATE()
                """, (user_id, assoc_hobby), fetchone=True)
                
                if not already_rejected:
                    h_info = execute_query(conn, "SELECT hobby_id, hobby_name FROM hobbies_catalog WHERE hobby_id = ?", (assoc_hobby,), fetchone=True, dict=True)
                    if h_info:
                        hobby_id = h_info['hobby_id']
                        hobby_name = h_info['hobby_name']
                else:
                    logging.info("Hobby del beacon ignorato: GIA' RIFIUTATO OGGI.")
            else:
                logging.info(f"Hobby del beacon scartato: preference_level={user_pref['preference_level']}.")

    # =========================================================================
    # 5. Fallback: preferito assoluto (Anti-Loop Globale)
    # =========================================================================
    if not hobby_id:
        hobby_data = execute_query(conn, """
            SELECT h.hobby_id, h.hobby_name 
            FROM user_hobbies uh
            JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
            WHERE uh.user_id = ?
            AND uh.preference_level > 2
            AND NOT EXISTS (
                SELECT 1 FROM activity_suggestions a
                WHERE a.hobby_id = uh.hobby_id 
                AND a.user_id = uh.user_id 
                AND a.status = 'REJECTED' 
                AND DATE(a.created_at) = CURDATE()
            )
            ORDER BY uh.preference_level DESC LIMIT 1
        """, (user_id,), fetchone=True, dict=True)
        if hobby_data:
            hobby_id = hobby_data['hobby_id']
            hobby_name = hobby_data['hobby_name']

    # =========================================================================
    # 6. BLOCCO ESAURIMENTO IDEE
    # =========================================================================
    if not hobby_id:
        background_tasks.add_task(send_simple_notification, user_id, "Pausa forzata! 😅", "Hai scartato tutte le tue attività preferite per oggi. Non posso proporti nient'altro, riposati!")
        return {"status": "blocked", "message": "Tutte le attivita preferite sono gia state rifiutate oggi."}

    # 7. Creazione suggerimento nel DB
    new_suggestion_id = str(uuid.uuid4())
    execute_query(conn, """
        INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
        VALUES (?, ?, ?, 30, 150, 'PROPOSED')
    """, (new_suggestion_id, user_id, hobby_id), fetch=False)

    # 8. Notifica context-aware
    background_tasks.add_task(
        send_shake_notification_task,
        user_id=user_id,
        suggestion_id=new_suggestion_id,
        hobby_name=hobby_name,
        zone_name=zone_name,
        minutes_in_zone=minutes_in_zone
    )

    return {"status": "success", "message": "Shake context-aware gestito in modo adattivo."}