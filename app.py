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
    "anthropic/claude-3-haiku-20240307"
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
    except Exception as e:
        return {
            "model": model_name,
            "status": "error",
            "content": f"[ERRORE] {type(e).__name__}: {str(e)}"
        }

async def run_query_flow(user_prompt: str, num_loops: int):
    for i in range(num_loops):
        # Esegue le chiamate in parallelo per questo ciclo
        tasks = [fetch_llm_response(model, user_prompt) for model in MODELS_TO_TEST]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                continue
            save_response(result['model'], user_prompt, result['content'], result['status'])
        
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

@app.route("/api/ask", methods=["POST"])
def ask():
    data = request.json or {}
    prompt = data.get("prompt", "").strip()
    num_loops = data.get("num_loops", 1)
    
    try:
        num_loops = int(num_loops)
    except ValueError:
        num_loops = 1
        
    if not prompt:
        return jsonify({"error": "Prompt vuoto"}), 400
        
    # Invia il task al thread in background asincrono per non bloccare la chiamata HTTP
    asyncio.run_coroutine_threadsafe(run_query_flow(prompt, num_loops), background_loop)
    return jsonify({"status": "processing", "message": "Richiesta avviata in background"})

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
