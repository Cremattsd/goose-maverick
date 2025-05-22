import json
import logging
import os
import requests
import smtplib
import sqlite3
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import openai
openai.api_key = os.getenv("OPENAI_API_KEY")
from tenacity import retry, stop_after_attempt, wait_exponential
from werkzeug.utils import secure_filename
from goose_parser_tools import (
    extract_text_from_image,
    extract_text_from_pdf,
    extract_exif_location,
    is_business_card,
    parse_ocr_text,
    suggest_field_mapping,
    map_fields,
)
from datetime import datetime, timedelta
import pandas as pd
import threading
import time

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
openai_client = openai

# SQLite for import history, user settings, and lead scores
DB_PATH = "import_history.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT,
    record_count INTEGER,
    success INTEGER,
    timestamp TEXT
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings (
    user_id TEXT PRIMARY KEY,
    email TEXT,
    event_alerts_enabled INTEGER,
    priority_filter TEXT,
    alarm_filter INTEGER,
    due_date_days INTEGER,
    mailchimp_api_key TEXT
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS lead_scores (
    user_id TEXT,
    contact_id TEXT,
    score INTEGER,
    timestamp TEXT,
    PRIMARY KEY (user_id, contact_id)
)''')
conn.commit()

# Event polling state
EVENT_POLLING_ENABLED = {}
EVENT_POLLING_THREADS = {}
LAST_EVENT_COUNT = {}
FIELD_DEFINITIONS = {}

# [Rest of your functions like load_field_definitions, realnex_post, realnex_get, etc., remain unchanged]

@app.route('/toggle-events', methods=['POST'])
def toggle_events():
    global EVENT_POLLING_ENABLED, EVENT_POLLING_THREADS
    try:
        data = request.json
        enable = data.get('enable', False)
        email = data.get('email', '').strip()
        priority_filter = data.get('priority_filter', 'high').lower()
        alarm_filter = data.get('alarm_filter', False)
        due_date_days = data.get('due_date_days', 7)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"message": "No token, Maverick! Lock in! 🔒"}), 401
        if not email:
            return jsonify({"message": "No email provided for alerts! 📧"}), 400

        user_id = get_user_id(token)
        EVENT_POLLING_ENABLED[user_id] = enable

        # Save user settings (removed mailchimp_api_key reference)
        cursor.execute('''INSERT OR REPLACE INTO user_settings 
                          (user_id, email, event_alerts_enabled, priority_filter, alarm_filter, due_date_days) 
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (user_id, email, 1 if enable else 0, priority_filter, 1 if alarm_filter else 0, due_date_days))
        conn.commit()

        if enable and user_id not in EVENT_POLLING_THREADS:
            EVENT_POLLING_THREADS[user_id] = threading.Thread(
                target=poll_events,
                args=(token, user_id, email, priority_filter, alarm_filter, due_date_days)
            )
            EVENT_POLLING_THREADS[user_id].daemon = True
            EVENT_POLLING_THREADS[user_id].start()
            return jsonify({"message": f"Event alerts enabled! Filtering for priority '{priority_filter}', alarms: {alarm_filter}, due within {due_date_days} days. 🔔"})
        elif not enable and user_id in EVENT_POLLING_THREADS:
            EVENT_POLLING_ENABLED[user_id] = False
            EVENT_POLLING_THREADS.pop(user_id, None)
            return jsonify({"message": "Event alerts disabled. Radar off! 📡"})
        else:
            return jsonify({"message": f"Event alerts already {'enabled' if enable else 'disabled'}!"})
    except Exception as e:
        logging.error(f"Toggle events error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

# [Rest of your routes like /ask, /suggest-mapping, /bulk-import, /upload-business-card, /dashboard-data, /summarize remain unchanged]

HELP_MESSAGE = """
🎯 *Goose-Maverick: Tech Stack & Usage Guide* 🎯
- *Backend*: Flask (Python) powers API routes (/ask, /upload-business-card, /bulk-import). Our jet engine!
- *Frontend*: Tailwind CSS for slick styling, Chart.js for gauges and dashboards, vanilla JS for drag-and-drop in a floating chat widget. The cockpit!
- *Parsing*: Goose uses pandas for Excel, pytesseract/pdf2image/Pillow for OCR, EXIF for geolocation. Data radar locked!
- *APIs*: RealNex V1 OData (/CrmOData) fetches user IDs and events; non-OData (/CrmContacts) syncs data. OpenAI (GPT-4o) runs chat, summaries, and lead scoring, ready for Grok 3!
- *Field Matching*: Pulls schemas from /api/v1/Crm/definitions or realnex_fields.json (4000+ fields!) to auto-match Contacts, Properties, Spaces, SaleComps.
- *Geolocation*: Photos’ EXIF data matches Properties/Spaces via latitude/longitude in OData queries.
- *New Features*: 
  - Dashboard at /dashboard shows import stats and AI-powered lead scores!
  - Toggle event polling with email alerts in Goose mode, with filters for due dates, priority, and alarms.
  - Real-time notifications in the chat widget via WebSocket!
- *Usage*:
  1. Switch to Goose mode, enter your RealNex Bearer token (from RealNex dashboard).
  2. Drag-and-drop photos (.png, .jpg), PDFs, or Excel (.xlsx) into the chat widget.
  3. For photos/PDFs, add notes and sync as Contacts or Properties. Photos geo-match to Properties/Spaces.
  4. For Excel, review/edit suggested field mappings, then import.
  5. Chat with Maverick for help, CRM queries (‘Show my events’), or commands like `!maverick`!
  6. Visit /dashboard to see import stats, lead scores, and request a summary.
  7. Toggle event polling in Goose mode for email alerts on new RealNex events, with filters.
- *Commands*: `!help` (this guide), `!maverick` (surprise), `!eject` (easter egg), `!deals` (SaleComps), `!events` (your events).
- *Deploy*: Dockerized, deployed to Render (mattys-drag-drop-app.onrender.com). Built to soar!
Ask ‘How do I sync SaleComps?’ or ‘How does geolocation work?’ for more! 😎
"""

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
