import os
import json
import logging
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, messaging

# 1. INIZIALIZZAZIONE FIREBASE (Eseguita al caricamento del modulo)
# Assicurati di avere il file JSON di Firebase nel percorso specificato nel .env
firebase_cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-adminsdk.json")
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(firebase_cred_path)
        firebase_admin.initialize_app(cred)
        logging.info("Firebase Admin SDK inizializzato con successo.")
except Exception as e:
    logging.error(f"Errore inizializzazione Firebase: {e}. Le notifiche push non partiranno.")


def generate_proactive_push_copy(intent: str) -> dict:
    """
    Interroga Gemini-2.5-Flash per generare il payload della notifica.
    Garantisce output JSON rigoroso e assenza totale di emoji.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)

    if intent == "fitness":
        context_instruction = "L'utente ha tempo libero ma e' sotto il suo obiettivo di calorie bruciate. Convincilo a fare movimento."
    else:
        context_instruction = "L'utente ha tempo libero e ha gia' completato gli obiettivi fisici. Suggerisci di dedicarsi a un hobby statico e rilassante."

    system_prompt = f"""
    Sei il motore proattivo dell'app FlowMate.
    {context_instruction}
    
    REGOLE RIGIDE:
    1. Lunghezza: Il campo 'body' massimo 15 parole. Il campo 'title' massimo 4 parole.
    2. Tono: Diretto, professionale e motivazionale.
    3. DIVIETO ASSOLUTO EMOJI: Non utilizzare MAI emoji o simboli, il testo deve essere pulito.
    
    Restituisci ESCLUSIVAMENTE un oggetto JSON con questa struttura:
    {{
        "title": "Titolo",
        "body": "Corpo del messaggio"
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
        logging.error(f"Errore Gemini Push Copy: {e}")
        # Testo di fallback garantito se le API falliscono
        if intent == "fitness":
            return {"title": "Tempo Libero", "body": "Hai una finestra temporale ottimale per completare l'obiettivo di movimento."}
        return {"title": "Obiettivi Raggiunti", "body": "Target fisici completati. E' il momento ideale per un'attivita' di recupero."}


def send_proactive_notification_task(user_id: str, intent: str, beacon_id: str):
    """
    Task asincrono eseguito da FastAPI in background.
    """
    logging.info(f"[Push Service] Avvio task proattivo. User: {user_id}, Intent: {intent}")
    
    # 1. Genera il testo
    push_data = generate_proactive_push_copy(intent)
    
    # 2. Costruisci il messaggio per Firebase
    # Nota: Utilizziamo il topic basato sull'user_id. L'app Android dovra' iscriversi a "topic_user_{user_id}"
    topic_name = f"user_{user_id.replace('-', '_')}" 
    
    message = messaging.Message(
        notification=messaging.Notification(
            title=push_data['title'],
            body=push_data['body'],
        ),
        data={
            "intent": intent,
            "beacon_id": beacon_id,
            "action": "PROACTIVE_SUGGESTION"
        },
        topic=topic_name
    )
    
    # 3. Invia ai server di Google FCM
    try:
        response = messaging.send(message)
        logging.info(f"[Push Service] Notifica inviata con successo. FCM Message ID: {response}")
    except Exception as e:
        logging.error(f"[Push Service] Errore invio Firebase FCM: {e}")