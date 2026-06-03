import asyncio
import os
import sqlite3
import json
import threading
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify
import litellm
from litellm import acompletion

# Carica le chiavi API dal file .env
load_dotenv()

app = Flask(__name__, template_folder='.', static_folder='.')

# Modelli da testare
MODELS_TO_TEST = [
    "gemini/gemini-2.5-flash",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4-5"
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
    except Exception as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE] {type(e).__name__}: {str(e)}"
        }

async def run_query_flow(user_prompt: str, num_loops: int, chat_id: str, base_question_id: str):
    import uuid
    # Recupera la cronologia una sola volta all'inizio della richiesta
    # in modo che tutte le ripetizioni condividano lo stesso contesto precedente
    model_histories = {}
    for model in MODELS_TO_TEST:
        model_histories[model] = get_chat_history(chat_id, model)
        
    for i in range(num_loops):
        # Genera un question_id unico per ciascun ciclo (ripetizione)
        iteration_question_id = base_question_id if i == 0 else f"q_{uuid.uuid4().hex[:12]}"
        
        tasks = []
        for model in MODELS_TO_TEST:
            history = model_histories[model]
            messages = history + [{"role": "user", "content": user_prompt}]
            tasks.append(fetch_llm_response(model, messages))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                continue
            save_response(result['model'], user_prompt, result['content'], result['status'], chat_id, iteration_question_id)
        
        # Esporta subito in JSON per visualizzare live
        export_to_json()
        
        # Attendi 30 secondi se ci sono altri cicli
        if i < num_loops - 1:
            await asyncio.sleep(30)

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Loop asincrono dedicato in background per gestire i flussi delle query
background_loop = asyncio.new_event_loop()
background_thread = threading.Thread(target=start_background_loop, args=(background_loop,), daemon=True)
background_thread.start()

# Aggiunge gli header CORS per consentire le chiamate da Apache (localhost) a Flask (localhost:5000)
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    return response

@app.route("/")
def index():
    return render_template("responses.html")

@app.route("/responses.json")
def responses_json():
    try:
        with open("responses.json", "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify([])

@app.route("/api/chats")
def get_chats():
    conn = sqlite3.connect("llm_responses.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        # Recupera chat_id unici con il primo prompt e data creazione
        cursor.execute('''
            SELECT chat_id, MIN(timestamp) as created_at, prompt 
            FROM responses 
            WHERE chat_id IS NOT NULL AND chat_id != ''
            GROUP BY chat_id 
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        chats = []
        for row in rows:
            chats.append({
                "chat_id": row["chat_id"],
                "created_at": row["created_at"],
                "title": row["prompt"][:40] + ("..." if len(row["prompt"]) > 40 else "")
            })
    except sqlite3.OperationalError:
        chats = []
    finally:
        conn.close()
    return jsonify(chats)

@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    conn = sqlite3.connect("llm_responses.db")
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM responses WHERE chat_id = ?", (chat_id,))
        conn.commit()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    export_to_json()
    return jsonify({"status": "success", "message": f"Chat {chat_id} eliminata"})

@app.route("/api/ask", methods=["POST"])
def ask():
    import uuid
    data = request.json or {}
    prompt = (data.get("prompt") or "").strip()
    num_loops = data.get("num_loops", 1)
    chat_id = (data.get("chat_id") or "").strip()
    
    try:
        num_loops = int(num_loops)
    except ValueError:
        num_loops = 1
        
    if not prompt:
        return jsonify({"error": "Prompt vuoto"}), 400
        
    # Se non viene passato un chat_id, ne creiamo uno nuovo
    if not chat_id:
        chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        
    # Genera un question_id unico per questo turn
    question_id = f"q_{uuid.uuid4().hex[:12]}"
        
    # Invia il task al thread in background asincrono per non bloccare la chiamata HTTP
    asyncio.run_coroutine_threadsafe(run_query_flow(prompt, num_loops, chat_id, question_id), background_loop)
    return jsonify({
        "status": "processing", 
        "chat_id": chat_id, 
        "question_id": question_id,
        "message": "Richiesta avviata in background"
    })

@app.route("/api/clear", methods=["POST"])
def clear_db():
    conn = sqlite3.connect("llm_responses.db")
    c = conn.cursor()
    c.execute("DELETE FROM responses")
    conn.commit()
    conn.close()
    
    with open("responses.json", "w", encoding="utf-8") as f:
        json.dump([], f)
        
    return jsonify({"status": "success", "message": "Database ripulito"})

if __name__ == "__main__":
    init_db()
    if not os.path.exists("responses.json"):
        with open("responses.json", "w", encoding="utf-8") as f:
            json.dump([], f)
    print("=" * 60)
    print("[AVVIO] FLASK BACKEND SERVER IN ESECUZIONE SU http://127.0.0.1:5000")
    print("=" * 60)
    app.run(debug=True, port=5000)
