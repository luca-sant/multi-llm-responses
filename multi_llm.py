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
    
    # 3. Anthropic Claude: "claude-haiku-4-5"
    "anthropic/claude-haiku-4-5",
    
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
    # Migrazione per aggiungere colonne chat_id e question_id se non esistono
    cursor.execute("PRAGMA table_info(responses)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'chat_id' not in columns:
        cursor.execute("ALTER TABLE responses ADD COLUMN chat_id TEXT")
    if 'question_id' not in columns:
        cursor.execute("ALTER TABLE responses ADD COLUMN question_id TEXT")
    conn.commit()
    conn.close()

def save_response(model, prompt, response, status, chat_id=None, question_id=None):
    conn = sqlite3.connect("llm_responses.db")
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO responses (timestamp, model, prompt, response, status, chat_id, question_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (timestamp, model, prompt, response, status, chat_id, question_id))
    conn.commit()
    conn.close()

def get_chat_history(chat_id: str, model_name: str):
    if not chat_id:
        return []
    conn = sqlite3.connect("llm_responses.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT prompt, response 
        FROM responses 
        WHERE chat_id = ? AND model = ? AND status = 'success' AND question_id IS NOT NULL
        GROUP BY question_id 
        ORDER BY id ASC
    ''', (chat_id, model_name))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        messages.append({"role": "user", "content": row["prompt"]})
        messages.append({"role": "assistant", "content": row["response"]})
    return messages

def export_to_json():
    try:
        conn = sqlite3.connect("llm_responses.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, timestamp, model, prompt, response, status, chat_id, question_id FROM responses ORDER BY id DESC")
        rows = cursor.fetchall()
        responses_list = []
        for row in rows:
            responses_list.append({
                "id": row[0],
                "timestamp": row[1],
                "model": row[2],
                "prompt": row[3],
                "response": row[4],
                "status": row[5],
                "chat_id": row[6] if len(row) > 6 else None,
                "question_id": row[7] if len(row) > 7 else None
            })
        with open("responses.json", "w", encoding="utf-8") as f:
            json.dump(responses_list, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    finally:
        if 'conn' in locals():
            conn.close()

async def fetch_llm_response(model_name: str, messages: list) -> dict:
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
    import uuid
    init_db()
    chat_id = f"cli_{uuid.uuid4().hex[:12]}"
    print("=" * 60)
    print("🤖 TEST MULTI-LLM IN PARALLELO E SALVATAGGIO SU DB")
    print(f"Session ID: {chat_id}")
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
        
        # Recupera la cronologia una sola volta all'inizio del blocco di invio
        model_histories = {}
        for model in MODELS_TO_TEST:
            model_histories[model] = get_chat_history(chat_id, model)

        total_results_count = 0
        for i in range(num_loops):
            print(f"⏳ Esecuzione ciclo {i+1} di {num_loops}...")
            
            # Genera un question_id unico per ciascun ciclo (ripetizione)
            question_id = f"q_{uuid.uuid4().hex[:12]}"
            
            # Creiamo i task asincroni con la cronologia specifica per ciascun modello
            tasks = []
            for model in MODELS_TO_TEST:
                history = model_histories[model]
                messages = history + [{"role": "user", "content": user_prompt}]
                tasks.append(fetch_llm_response(model, messages))
                
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            print("-" * 60)
            for result in results:
                if isinstance(result, Exception):
                    print(f"Errore fatale imprevisto: {result}")
                    continue
                    
                model_name = result['model']
                status = result['status']
                content = result['content']
                
                # Salvataggio immediato sul DB con chat_id e question_id
                save_response(model_name, user_prompt, content, status, chat_id, question_id)
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
