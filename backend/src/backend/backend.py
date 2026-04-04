import logging
import os
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.exceptions import RequestValidationError
from endpoints.chat.chat import router as chat_router
from db.pool import init_pool, get_pool
from exceptions import request_validation_exception_handler

# Importazione dei router dai rispettivi domini
from endpoints.users.users import router as users_router
from endpoints.hobbies.hobbies import router as hobbies_router
from endpoints.schedule.schedule import router as schedule_router
from endpoints.biometrics.biometrics import router as biometrics_router
from endpoints.activities.activities import router as activities_router
from endpoints.beacons.beacons import router as beacons_router
from endpoints.presence.presence import router as presence_router
from endpoints.calendar.calendar import router as calendar_router
from endpoints.dashboard.dashboard import router as dashboard_router
# Lettura delle variabili d'ambiente per la configurazione del database
db_host = os.getenv("DB_HOST", "flowmate-db")
db_port = int(os.getenv("DB_PORT", 3306))
db_user = os.getenv("DB_USER", "")
db_password = os.getenv("DB_PASSWORD", "")
db_name = os.getenv("DB_NAME", "flowmate_db")

if not db_user or not db_password:
    raise RuntimeError("Environment variables DB_USER and DB_PASSWORD must be set.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- FASE DI STARTUP ---
    # Inizializzazione del pool di connessioni prima di accettare richieste
    init_pool(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name
    )
    
    # Cede il controllo a FastAPI
    yield
    
    # --- FASE DI TEARDOWN ---
    # Deallocazione sicura delle risorse al termine dell'esecuzione
    try:
        pool = get_pool()
        pool.close()
    except RuntimeError:
        # Ignora l'eccezione se il pool non è mai stato inizializzato
        pass

# Istanziazione dell'applicazione FastAPI
app = FastAPI(lifespan=lifespan)

# Metadati per la documentazione automatica (Swagger UI)
app.title = "Backend Flowmate API"
app.description = "API for managing Flowmate project."

# Registrazione del gestore di eccezioni personalizzato per la validazione
app.exception_handler(RequestValidationError)(request_validation_exception_handler)

# Registrazione dei router nell'applicazione principale
app.include_router(users_router)
app.include_router(hobbies_router)
app.include_router(schedule_router)
app.include_router(biometrics_router)
app.include_router(activities_router)
app.include_router(beacons_router)
app.include_router(presence_router)
app.include_router(chat_router)
app.include_router(calendar_router)
app.include_router(dashboard_router)
