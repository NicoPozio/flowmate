import google.generativeai as genai

# INCOLLA QUI LA TUA CHIAVE REALE TRA LE VIRGOLETTE
CHIAVE_DI_TEST = "AIzaSyDlzb5qflWFkh1RKhO3DXlth_jJ3F4bOuo" 

genai.configure(api_key=CHIAVE_DI_TEST)

print("--- LISTA MODELLI DISPONIBILI PER LA TUA CHIAVE ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Modello: {m.name}")
except Exception as e:
    print(f"Errore nel recupero modelli: {e}")