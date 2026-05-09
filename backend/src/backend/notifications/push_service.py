import os
import json
import logging
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, messaging

# 1. INIZIALIZZAZIONE FIREBASE
firebase_cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-adminsdk.json")
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_cred_path)
        firebase_admin.initialize_app(cred)
        logging.info("Firebase Admin SDK inizializzato con successo.")
except Exception as e:
    logging.error(f"Errore inizializzazione Firebase: {e}.")

def generate_proactive_push_copy(intent: str, hobby_name: str, zone_name: str = None, minutes_in_zone: int = 0) -> dict:
    """
    Task 3.2: Genera payload notifica usando l'hobby e il CONTESTO AMBIENTALE.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)

    if intent == "fitness":
        context_instruction = f"L'utente deve raggiungere il suo obiettivo fisico. Suggerisci caldamente di fare {hobby_name}."
    else:
        context_instruction = f"L'utente è in regola con i passi. Suggerisci di rilassarsi facendo {hobby_name}."

    context_ambientale = ""
    if zone_name:
        context_ambientale = f"L'utente si trova in '{zone_name}' da {minutes_in_zone} minuti. FAI RIFERIMENTO ALLA STANZA E AL TEMPO TRASCORSO NELLA FRASE."

    system_prompt = f"""
    Sei FlowMate, un compagno di benessere amichevole.
    {context_instruction}
    {context_ambientale}
    
    REGOLE RIGIDE:
    1. Stile: Colloquiale, amichevole, UNA SOLA FRASE fluida (max 20 parole).
    2. Titolo: Accattivante, max 4 parole.
    3. NO EMOJI: Non usarne mai.
    
    Restituisci JSON:
    {{
        "title": "Titolo",
        "body": "Messaggio naturale che nomina l'attività suggerita"
    }}
    """

    try:
        model = genai.GenerativeModel(
            model_name='gemini-2.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(system_prompt)
        return json.loads(response.text)
    except Exception as e:
        logging.error(f"Errore Gemini Push: {e}")
        fallback_body = f"Sei in {zone_name} da {minutes_in_zone} min. Facciamo {hobby_name}?" if zone_name else f"Che ne dici di dedicare un po' di tempo a {hobby_name}?"
        return {
            "title": "Momento FlowMate", 
            "body": fallback_body
        }

def send_proactive_notification_task(user_id: str, intent: str, beacon_id: str, suggestion_id: str, hobby_name: str, zone_name: str = None, minutes_in_zone: int = 0):
    """
    Invia la notifica includendo l'ID suggerimento e il contesto (Task 3.1)
    """
    logging.info(f"[Push Service] Generazione notifica per {hobby_name} in {zone_name}")
    push_data = generate_proactive_push_copy(intent, hobby_name, zone_name, minutes_in_zone)
    topic_name = f"user_{user_id.replace('-', '_')}" 
    
    message = messaging.Message(
        data={
            "title": push_data['title'],
            "body": push_data['body'],
            "intent": intent,
            "beacon_id": beacon_id,
            "action": "PROACTIVE_SUGGESTION",
            "suggestion_id": suggestion_id
        },
        android=messaging.AndroidConfig(priority='high'),
        topic=topic_name
    )
    
    try:
        response = messaging.send(message)
        logging.info(f"[Push Service] Notifica inviata: {response}")
    except Exception as e:
        logging.error(f"[Push Service] Errore Firebase: {e}")

def send_simple_notification(user_id: str, title: str, body: str):
    """
    Invia una notifica Firebase di solo testo (senza bottoni).
    """
    topic_name = f"user_{user_id.replace('-', '_')}" 
    
    message = messaging.Message(
        data={
            "title": title,
            "body": body,
            "action": "INFO_REMINDER" 
        },
        android=messaging.AndroidConfig(priority='high'),
        topic=topic_name
    )
    
    try:
        messaging.send(message)
        logging.info(f"Notifica standard inviata a {user_id}: {title}")
    except Exception as e:
        logging.error(f"Errore invio notifica standard: {e}")

def send_shake_notification_task(user_id: str, suggestion_id: str, hobby_name: str, zone_name: str = None, minutes_in_zone: int = 0):
    """
    Invia la notifica specifica per lo shake, contestuale.
    """
    logging.info(f"[Push Service] Generazione notifica SHAKE per {hobby_name}")
    
    push_data = generate_proactive_push_copy("fitness", hobby_name, zone_name, minutes_in_zone)
    topic_name = f"user_{user_id.replace('-', '_')}" 
    
    message = messaging.Message(
        data={
            "title": push_data['title'],
            "body": push_data['body'],
            "action": "SHAKE_SUGGESTION",
            "suggestion_id": suggestion_id  
        },
        android=messaging.AndroidConfig(priority='high'),
        topic=topic_name
    )
    
    try:
        response = messaging.send(message)
        logging.info(f"[Push Service] Notifica SHAKE inviata: {response}")
    except Exception as e:
        logging.error(f"[Push Service] Errore Firebase (Shake): {e}")