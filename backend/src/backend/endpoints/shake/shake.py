from fastapi import APIRouter, BackgroundTasks, Path, Depends, HTTPException
import uuid
import logging
import mariadb
from datetime import date
from db.mariadb import db_connection, execute_query

# IMPORT CORRETTO: Importiamo la funzione specifica per lo shake
from notifications.push_service import send_shake_notification_task, send_simple_notification

router = APIRouter(tags=["Shake"])

@router.post("/users/{user_id}/shake")
async def trigger_shake_action(
    background_tasks: BackgroundTasks,
    user_id: str = Path(...),
    conn: mariadb.Connection = Depends(db_connection)
):
    today_str = date.today().isoformat()

    # 1. Controlliamo se esiste un'attività PROPOSTA o ACCETTATA per oggi
    existing_activity = execute_query(conn, """
        SELECT status FROM activity_suggestions 
        WHERE user_id = ? AND status IN ('PROPOSED', 'ACCEPTED') AND DATE(created_at) = ?
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, today_str), fetchone=True, dict=True)

    if existing_activity:
        status = existing_activity['status']
        
        # Gestione dei casi di blocco con notifiche di promemoria (SENZA BOTTONI)
        if status == 'PROPOSED':
            title = "Promemoria FlowMate 📌"
            body = "Hai una attività già proposta da accettare!"
        else: # ACCEPTED
            title = "Attività in corso 🏃"
            body = "Devi ancora finire l'attività di prima!"

        # Senza l'ID, NotificationHelper.kt non mostrerà i pulsanti Accetta/Rifiuta.
        background_tasks.add_task(
            send_simple_notification, 
            user_id, 
            title, 
            body
        )
        
        return {"status": "success", "message": "Reminder sent without buttons."}

    # --- SE LO STATO È LIBERO: LOGICA ORIGINALE ---

    # 2. Recuperiamo l'hobby preferito
    hobby_data = execute_query(conn, """
        SELECT h.hobby_id, h.hobby_name 
        FROM user_hobbies uh
        JOIN hobbies_catalog h ON uh.hobby_id = h.hobby_id
        WHERE uh.user_id = ?
        ORDER BY uh.preference_level DESC LIMIT 1
    """, (user_id,), fetchone=True, dict=True)

    hobby_id = hobby_data['hobby_id'] if hobby_data else 1
    hobby_name = hobby_data['hobby_name'] if hobby_data else "una passeggiata"

    # 3. Generiamo il nuovo suggestion_id e inseriamo nel DB
    new_suggestion_id = str(uuid.uuid4())
    try:
        execute_query(conn, """
            INSERT INTO activity_suggestions (suggestion_id, user_id, hobby_id, suggested_duration_minutes, expected_kcal, status)
            VALUES (?, ?, ?, ?, ?, 'PROPOSED')
        """, (new_suggestion_id, user_id, hobby_id, 30, 150), fetch=False)
    except Exception as e:
        logging.error(f"Errore DB Shake: {e}")
        raise HTTPException(status_code=500, detail="Errore interno del server")

    # 4. Background Task per Gemini (Usa la funzione corretta e inclusa l'ID per i bottoni)
    background_tasks.add_task(
        send_shake_notification_task,
        user_id=user_id,
        suggestion_id=new_suggestion_id,
        hobby_name=hobby_name
    )

    return {"status": "success", "message": "Shake gesture accepted, AI is working."}