from typing import Optional
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
import logging
import functools

class Error(BaseModel):
    detail: str
    field: Optional[str]

def handle_exceptions(default_status_code=500, log_errors=True):
    """
    Decoratore per convertire eccezioni comuni in HTTPException.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)

            except HTTPException as http_exc:
                raise http_exc

            except (ValidationError, ValueError) as e:
                raise HTTPException(status_code=422, detail=str(e))

            except Exception as e:
                if log_errors:
                    logging.exception(f"Unexpected error in function '{func.__name__}'")
                raise HTTPException(status_code=default_status_code, detail="Errore interno al server")

        return wrapper

    return decorator

def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    
    if errors:
        first_error = errors[0]
        msg = first_error.get("msg", "Errore di validazione")
        
        # Estrai il campo (es. da ['body', 'password'] -> 'password')
        loc = first_error.get("loc", [])
        field = loc[-1] if loc else None
    else:
        msg = "Errore di validazione"
        field = None

    response = {"detail": msg}
    if field:
        response["field"] = field

    return JSONResponse(status_code=422, content=response)