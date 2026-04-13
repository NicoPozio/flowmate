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

def generate_proactive_push_copy(intent: str, hobby_name: str) -> dict:
    """
    Interroga Gemini per generare il payload della notifica usando l'hobby suggerito.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)

    if intent == "fitness":
        context_instruction = f"L'utente deve raggiungere il suo obiettivo fisico. Suggerisci caldamente di fare {hobby_name}."
    else:
        context_instruction = f"L'utente è in regola con i passi. Suggerisci di rilassarsi facendo {hobby_name}."

    system_prompt = f"""
    Sei FlowMate, un compagno di benessere amichevole.
    {context_instruction}
    
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
        return {
            "title": "Momento FlowMate", 
            "body": f"Che ne dici di dedicare un po' di tempo a {hobby_name}?"
        }

def send_proactive_notification_task(user_id: str, intent: str, beacon_id: str, suggestion_id: str, hobby_name: str):
    """
    Invia la notifica includendo l'ID suggerimento per i bottoni dello smartwatch.
    """
    logging.info(f"[Push Service] Generazione notifica per {hobby_name}")
    push_data = generate_proactive_push_copy(intent, hobby_name)
    topic_name = f"user_{user_id.replace('-', '_')}" 
    
    message = messaging.Message(
        notification=messaging.Notification(
            title=push_data['title'],
            body=push_data['body'],
        ),
        data={
            "intent": intent,
            "beacon_id": beacon_id,
            "action": "PROACTIVE_SUGGESTION",
            "suggestion_id": suggestion_id  # Collegamento per i bottoni Android
        },
        topic=topic_name
    )
    
    try:
        response = messaging.send(message)
        logging.info(f"[Push Service] Notifica inviata: {response}")
    except Exception as e:
        logging.error(f"[Push Service] Errore Firebase: {e}")