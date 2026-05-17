import sqlite3
import os

def generate_html():
    if not os.path.exists("llm_responses.db"):
        print("Il database 'llm_responses.db' non esiste ancora. Avvia prima multi_llm.py per generare risposte.")
        return

    conn = sqlite3.connect("llm_responses.db")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, timestamp, model, prompt, response, status FROM responses ORDER BY id DESC")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        print("La tabella 'responses' non esiste. Assicurati che lo script multi_llm.py abbia salvato almeno una risposta.")
        conn.close()
        return
        
    conn.close()

    html_content = """
    <!DOCTYPE html>
    <html lang="it">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="description" content="Dashboard delle risposte generate dai modelli LLM in parallelo">
        <title>LLM Responses Dashboard</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-color: #0f172a;
                --text-color: #f8fafc;
                --card-bg: rgba(30, 41, 59, 0.7);
                --card-border: rgba(255, 255, 255, 0.1);
                --accent: #3b82f6;
                --success: #10b981;
                --error: #ef4444;
            }
            
            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                padding: 0;
                font-family: 'Inter', sans-serif;
                background: var(--bg-color);
                color: var(--text-color);
                min-height: 100vh;
                background-image: 
                    radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.15), transparent 25%),
                    radial-gradient(circle at 85% 30%, rgba(16, 185, 129, 0.15), transparent 25%);
                background-attachment: fixed;
            }

            header {
                padding: 2rem;
                text-align: center;
                background: rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(12px);
                border-bottom: 1px solid var(--card-border);
                position: sticky;
                top: 0;
                z-index: 10;
            }

            h1 {
                margin: 0;
                font-weight: 700;
                font-size: 2.5rem;
                background: linear-gradient(135deg, #60a5fa, #34d399);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                letter-spacing: -0.05em;
            }

            p.subtitle {
                color: #94a3b8;
                margin-top: 0.5rem;
                font-size: 1.1rem;
            }

            main {
                max-width: 1400px;
                margin: 3rem auto;
                padding: 0 1.5rem;
                display: grid;
                gap: 2rem;
            }

            .card {
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                border-radius: 20px;
                padding: 1.75rem;
                backdrop-filter: blur(16px);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                flex-direction: column;
            }

            .card:hover {
                transform: translateY(-8px);
                box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
                border-color: rgba(255, 255, 255, 0.2);
            }

            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 1rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid var(--card-border);
            }

            .model-name {
                font-weight: 700;
                color: var(--text-color);
                font-size: 1.15rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .model-name::before {
                content: '';
                display: block;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: var(--accent);
                box-shadow: 0 0 10px var(--accent);
            }

            .status {
                padding: 0.35rem 1rem;
                border-radius: 9999px;
                font-size: 0.8rem;
                font-weight: 600;
                letter-spacing: 0.05em;
                text-transform: uppercase;
            }

            .status.success {
                background: rgba(16, 185, 129, 0.15);
                color: var(--success);
                border: 1px solid rgba(16, 185, 129, 0.3);
            }

            .status.error {
                background: rgba(239, 68, 68, 0.15);
                color: var(--error);
                border: 1px solid rgba(239, 68, 68, 0.3);
            }

            .timestamp {
                font-size: 0.85rem;
                color: #64748b;
                margin-bottom: 1.5rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .prompt {
                font-weight: 600;
                margin-bottom: 1rem;
                color: #e2e8f0;
                font-size: 1.05rem;
                line-height: 1.5;
            }

            .prompt span {
                color: var(--accent);
            }

            .response {
                color: #cbd5e1;
                font-size: 0.95rem;
                line-height: 1.7;
                white-space: pre-wrap;
                background: rgba(0, 0, 0, 0.3);
                padding: 1.25rem;
                border-radius: 12px;
                flex-grow: 1;
                max-height: 350px;
                overflow-y: auto;
                border: 1px solid rgba(255,255,255,0.05);
            }
            
            /* Custom Scrollbar for response box */
            .response::-webkit-scrollbar {
                width: 8px;
            }
            .response::-webkit-scrollbar-track {
                background: rgba(0, 0, 0, 0.1);
                border-radius: 8px;
            }
            .response::-webkit-scrollbar-thumb {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 8px;
            }
            .response::-webkit-scrollbar-thumb:hover {
                background: rgba(255, 255, 255, 0.2);
            }
            
            .empty-state {
                grid-column: 1 / -1;
                text-align: center;
                padding: 4rem;
                background: var(--card-bg);
                border-radius: 20px;
                border: 1px dashed var(--card-border);
            }
        </style>
    </head>
    <body>
        <header>
            <h1>LLM Responses Dashboard</h1>
            <p class="subtitle">Monitoraggio in tempo reale dei prompt asincroni</p>
        </header>
        <main>
    """
    
    if not rows:
        html_content += """
            <div class="empty-state">
                <h2>Nessun dato presente</h2>
                <p>Non ci sono ancora risposte nel database. Usa lo script Python per inviare domande.</p>
            </div>
        """
    else:
        for row in rows:
            db_id, timestamp, model, prompt, response, status = row
            status_class = 'success' if status == 'success' else 'error'
            
            # Scappa caratteri HTML basic
            prompt_safe = str(prompt).replace("<", "&lt;").replace(">", "&gt;")
            response_safe = str(response).replace("<", "&lt;").replace(">", "&gt;")
            
            html_content += f"""
                <div class="card">
                    <div class="card-header">
                        <span class="model-name">{model.split('/')[-1].upper()}</span>
                        <span class="status {status_class}">{status}</span>
                    </div>
                    <div class="timestamp">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        {timestamp}
                    </div>
s                    <div class="response">{response_safe}</div>
                </div>
            """
        
    html_content += """
        </main>
    </body>
    </html>
    """
    
    with open("responses.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print("Dashboard HTML generata con successo in 'responses.html'")

if __name__ == "__main__":
    generate_html()
