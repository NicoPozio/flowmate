import mariadb
from fastapi import HTTPException

from db.pool import get_pool

def db_connection():
    """Return a connection to the database, and close it when done."""
    conn = get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()

def execute_query(
    connection: mariadb.Connection, 
    query: str, 
    params: tuple = (), 
    fetchone: bool = False,
    fetch: bool = True, 
    dict: bool = False
):
    """Execute a query and return the results based on fetch parameters."""
    results = None
    try:
        with connection.cursor(dictionary=dict) as cursor:
            cursor.execute(query, params)
            
            # Identificazione del tipo di operazione
            query_upper = query.strip().upper()

            # 1. Gestione del Commit per operazioni di scrittura
            if query_upper.startswith(("INSERT", "UPDATE", "DELETE")):
                connection.commit()
                
                # Se è un INSERT, non stiamo facendo fetch e la tabella usa AUTO_INCREMENT,
                # salviamo l'ID generato. Se usa UUID, il valore sarà 0 (che i router ignoreranno).
                if query_upper.startswith("INSERT") and not fetch:
                    return cursor.lastrowid

            # 2. Gestione dell'estrazione per operazioni di lettura
            if fetch:
                if fetchone:
                    results = cursor.fetchone()
                else:
                    results = cursor.fetchall()

    except mariadb.Error as e:
        # Logging granulare dell'errore del database
        raise HTTPException(status_code=500, detail=f"Errore interno del database: {e}")
    except Exception as e:
        # Gestione di errori generici di esecuzione
        raise HTTPException(status_code=500, detail=f"Errore nell'esecuzione della query: {e}")
    
    return results