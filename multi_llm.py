import asyncio
import os
import sqlite3
import json
from datetime import datetime
from dotenv import load_dotenv
import litellm
from litellm import acompletion

# Carica le variabili d'ambiente dal file .env
load_dotenv()

# ==============================================================================
# CONFIGURAZIONE DEI MODELLI GRATUITI O A BASSO COSTO (TRAMITE CREDITI)
# ==============================================================================
# In LiteLLM, il formato è "provider/nome-modello"
MODELS_TO_TEST = [
    # 1. Google Gemini: "gemini-2.5-flash"
    "gemini/gemini-2.5-flash",
    
    # 2. OpenAI: "gpt-4o-mini"
   # "openai/gpt-4o-mini",
    
    # 3. Anthropic Claude: "claude-3-haiku-20240307"
   # "anthropic/claude-3-haiku-20240307",
    
    # 4. OpenRouter (Opzionale)
    # "openrouter/meta-llama/llama-3-8b-instruct:free",
]

litellm.set_verbose = False

def init_db():
    conn = sqlite3.connect("llm_responses.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_response(model, prompt, response, status):
    conn = sqlite3.connect("llm_responses.db")
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO responses (timestamp, model, prompt, response, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (timestamp, model, prompt, response, status))
    conn.commit()
    conn.close()

def export_to_json():
    try:
        conn = sqlite3.connect("llm_responses.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, model, prompt, response, status FROM responses ORDER BY id DESC")
        rows = cursor.fetchall()
        responses_list = []
        for row in rows:
            responses_list.append({
                "id": row[0],
                "timestamp": row[1],
                "model": row[2],
                "prompt": row[3],
                "response": row[4],
                "status": row[5]
            })
        with open("responses.json", "w", encoding="utf-8") as f:
            json.dump(responses_list, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    finally:
        if 'conn' in locals():
            conn.close()

async def fetch_llm_response(model_name: str, user_prompt: str) -> dict:
    messages = [{"role": "user", "content": user_prompt}]
    
    try:
        response = await acompletion(
            model=model_name,
            messages=messages,
            timeout=30 
        )
        answer_text = response.choices[0].message.content.strip()
        return {
            "model": model_name,
            "status": "success",
            "content": answer_text
        }
        
    except litellm.Timeout as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE TIMEOUT] ({str(e)})"
        }
    except litellm.AuthenticationError as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE AUTENTICAZIONE] ({str(e)})"
        }
    except litellm.RateLimitError as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE RATE LIMIT] ({str(e)})"
        }
    except Exception as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE GENERICO] {type(e).__name__}: {str(e)}"
        }


async def main():
    init_db()
    print("=" * 60)
    print("🤖 TEST MULTI-LLM IN PARALLELO E SALVATAGGIO SU DB")
    print("=" * 60)
    
    while True:
        print("\nScrivi la tua domanda da inviare ai modelli (o 'exit' per uscire):")
        user_prompt = input(">>> ")
        
        if user_prompt.lower().strip() in ['exit', 'quit', 'esci']:
            break
            
        if not user_prompt.strip():
            continue

        print("\nQuante risposte vuoi generare per ogni modello?")
        try:
            num_loops = int(input(">>> "))
        except ValueError:
            print("Numero non valido, imposto a 1.")
            num_loops = 1

        print(f"\n🚀 Invio della domanda ai modelli ({num_loops} volte, con 30 secondi di attesa tra un ciclo e l'altro)...\n")
        
        total_results_count = 0
        for i in range(num_loops):
            print(f"⏳ Esecuzione ciclo {i+1} di {num_loops}...")
            
            # Creiamo i task solo per questo specifico ciclo (in parallelo per i diversi modelli)
            tasks = [fetch_llm_response(model, user_prompt) for model in MODELS_TO_TEST]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            print("-" * 60)
            for result in results:
                if isinstance(result, Exception):
                    print(f"Errore fatale imprevisto: {result}")
                    continue
                    
                model_name = result['model']
                status = result['status']
                content = result['content']
                
                # Salvataggio immediato sul DB
                save_response(model_name, user_prompt, content, status)
                total_results_count += 1
                
                print(f"🔸 MODELLO: {model_name.upper()}")
                if status == "success":
                    print(f"RISPOSTA:\n{content}")
                else:
                    print(f"PROBLEMA:\n{content}")
                print("-" * 60)
            
            # Esportiamo live in JSON dopo ogni ciclo così la dashboard si aggiorna subito!
            export_to_json()
            
            # Se ci sono altri cicli da fare, attendiamo 30 secondi
            if i < num_loops - 1:
                print(f"⏱️ Attesa di 30 secondi prima del prossimo invio per rispettare i limiti gratuiti (Free Tier)...")
                await asyncio.sleep(30)
                print()
                
        print(f"\n✅ Fine sessione! {total_results_count} risposte gestite con successo.")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEsecuzione interrotta.")
