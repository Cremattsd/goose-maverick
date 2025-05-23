import json
import logging
import os
import httpx
import smtplib
import sqlite3
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import openai
import asyncio
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
cursor.execute('CREATE INDEX IF NOT EXISTS idx_imports_timestamp ON imports (timestamp)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_lead_scores_user_id ON lead_scores (user_id)')
conn.commit()

# Event polling state
EVENT_POLLING_ENABLED = {}
EVENT_POLLING_THREADS = {}
LAST_EVENT_COUNT = {}
FIELD_DEFINITIONS = {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def load_field_definitions(token):
    global FIELD_DEFINITIONS
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{REALNEX_API_BASE}/Crm/definitions", headers=headers)
            response.raise_for_status()
            tables = response.json()
            for table in tables:
                response = await client.get(f"{REALNEX_API_BASE}/Crm/definitions/{table}", headers=headers)
                response.raise_for_status()
                FIELD_DEFINITIONS[table] = response.json()
    except Exception as e:
        logging.warning(f"API failed, loading realnex_fields.json: {str(e)}")
        with open("realnex_fields.json", "r") as f:
            FIELD_DEFINITIONS = json.load(f)
    return FIELD_DEFINITIONS

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
        response.raise_for_status()
        return response.status_code, response.json() if response.content else {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def realnex_get(endpoint, token, is_odata=False):
    headers = {"Authorization": f"Bearer {token}"}
    base = ODATA_BASE if is_odata else REALNEX_API_BASE
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base}/{endpoint}", headers=headers)
        response.raise_for_status()
        return response.status_code, response.json().get('value', response.json())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def get_user_id(token):
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{REALNEX_API_BASE}/Client?api-version=1.0", headers=headers)
        response.raise_for_status()
        return response.json().get('key')

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def match_property_by_geolocation(lat, lon, token):
    headers = {"Authorization": f"Bearer {token}"}
    query = f"Properties?$filter=latitude eq {lat} and longitude eq {lon}&$top=1"
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ODATA_BASE}/{query}", headers=headers)
        response.raise_for_status()
        properties = response.json().get('value', [])
        return properties[0].get('crm_property_key') if properties else None

def send_email_alert(subject, body, to_email):
    try:
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        smtp_user = os.getenv("SMTP_USER")
        smtp_password = os.getenv("SMTP_PASSWORD")
        if not smtp_user or not smtp_password:
            logging.error("SMTP credentials not set")
            return

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = to_email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
        logging.info(f"Email sent to {to_email}")
    except Exception as e:
        logging.error(f"Email alert failed: {str(e)}")

async def score_leads(token, user_id):
    try:
        status, contacts = await realnex_get(f"Contacts?$filter=userId eq {user_id}&$top=50", token, is_odata=True)
        if status != 200:
            return

        status, events = await realnex_get(f"Events?$filter=userId eq {user_id}&$top=50", token, is_odata=True)
        if status != 200:
            return

        contact_data = []
        for contact in contacts:
            contact_id = contact.get('crm_contact_key')
            contact_events = [e for e in events if e.get('contactId') == contact_id]
            event_count = len(contact_events)
            recent_activity = any(
                datetime.strptime(e.get('dueDate', datetime.now().isoformat()), '%Y-%m-%dT%H:%M:%S') > 
                datetime.now() - timedelta(days=30) for e in contact_events
            )
            contact_data.append({
                "contact_id": contact_id,
                "name": contact.get('name', 'Unknown'),
                "event_count": event_count,
                "recent_activity": recent_activity,
                "properties_owned": contact.get('properties', [])
            })

        prompt = f"""
        You are a lead scoring AI for a commercial real estate chatbot. Score each contact as a lead from 0 to 100 based on their activity:
        - Higher event count = higher score (max 40 points for 5+ events)
        - Recent activity (last 30 days) = +30 points
        - Properties owned = +5 points per property (max 30 points)
        Return a JSON list of {{"contact_id": "id", "score": score}} entries.
        Data: {json.dumps(contact_data, indent=2)}
        """
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You’re Maverick, a sassy real estate chatbot with Top Gun vibes."},
                {"role": "user", "content": prompt}
            ]
        )
        scores = json.loads(response.choices[0].message.content)

        current_time = datetime.now().isoformat()
        for score_entry in scores:
            contact_id = score_entry['contact_id']
            score = score_entry['score']
            cursor.execute('''INSERT OR REPLACE INTO lead_scores 
                              (user_id, contact_id, score, timestamp) 
                              VALUES (?, ?, ?, ?)''',
                           (user_id, contact_id, score, current_time))
        conn.commit()

        socketio.emit('lead_scores_updated', {'user_id': user_id}, namespace='/chat')
    except Exception as e:
        logging.error(f"Lead scoring error for user {user_id}: {str(e)}")

async def poll_events(token, user_id, email, priority_filter, alarm_filter, due_date_days):
    global LAST_EVENT_COUNT
    LAST_EVENT_COUNT[user_id] = LAST_EVENT_COUNT.get(user_id, 0)
    while EVENT_POLLING_ENABLED.get(user_id, False):
        try:
            status, events = await realnex_get(f"Events?$filter=userId eq {user_id}", token, is_odata=True)
            if status != 200:
                await asyncio.sleep(300)
                continue

            current_time = datetime.now()
            due_threshold = current_time + timedelta(days=due_date_days)
            new_events = []
            for event in events:
                event_due_date = datetime.strptime(event.get('dueDate', current_time.isoformat()), '%Y-%m-%dT%H:%M:%S')
                event_priority = event.get('priority', 'Low')
                has_alarm = event.get('hasAlarm', False)

                due_soon = event_due_date <= due_threshold
                priority_match = (priority_filter.lower() == 'any' or event_priority.lower() == priority_filter.lower())
                alarm_match = (not alarm_filter or has_alarm)

                if due_soon and priority_match and alarm_match:
                    new_events.append(event)

            event_count = len(new_events)
            if event_count > LAST_EVENT_COUNT[user_id]:
                new_event_count = event_count - LAST_EVENT_COUNT[user_id]
                message = f"You've got {new_event_count} events due soon! 🛫 Check 'em out!"
                send_email_alert(
                    "RealNex Event Due Alert",
                    f"Maverick here! {message}\n\n{json.dumps(new_events[-new_event_count:], indent=2)}",
                    email
                )
                socketio.emit('notification', {'message': message}, namespace='/chat')
                LAST_EVENT_COUNT[user_id] = event_count

            await score_leads(token, user_id)
            await asyncio.sleep(300)  # Poll every 5 minutes
        except Exception as e:
            logging.error(f"Event}
            logging.error(f"Event polling error for user {user_id}: {str(e)}")
            await asyncio.sleep(300)

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'dashboard.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/validate-token', methods=['POST'])
async def validate_token():
    try:
        token = request.json.get('token', '').strip()
        if not token:
            return jsonify({"valid": False, "error": "No token provided"}), 400
        status, _ = await realnex_get("Client?api-version=1.0", token)
        return jsonify({"valid": status == 200})
    except Exception as e:
        logging.error(f"Token validation error: {str(e)}")
        return jsonify({"valid": False, "error": str(e)}), 500

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip().lower()
        if not user_message:
            return jsonify({"answer": "Gimme something to work with, Goose! 😎"})
        if user_message == "!help" or "tech stack" in user_message or "how to use" in user_message:
            return jsonify({"answer": HELP_MESSAGE})
        if user_message == "!maverick":
            return jsonify({"answer": "I feel the need… the need for leads! 🛩️ https://media.giphy.com/media/3o7aDcz7XVeM6fW8zC/giphy.gif"})
        if user_message == "!eject":
            return jsonify({"answer": "Eject, eject, eject! Goose is outta here! 🪂 https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"})
        if user_message == "!clearturbulence":
            return jsonify({"answer": "Turbulence cleared! Skies are blue, Goose! 🛫 https://media.giphy.com/media/3o7TKsQ8vXh8lTJyZw/giphy.gif"})
        if user_message == "!deals":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            status, deals = asyncio.run(realnex_get("SaleComps?$top=3", token, is_odata=True))
            return jsonify({"answer": f"Latest deals: {json.dumps(deals, indent=2)}" if status == 200 else "Turbulence fetching deals!"})
        if user_message == "!events":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            user_id = asyncio.run(get_user_id(token))
            status, events = asyncio.run(realnex_get(f"Events?$filter=userId eq {user_id}&$top=5", token, is_odata=True))
            return jsonify({"answer": f"Your events: {json.dumps(events, indent=2)}" if status == 200 else "Turbulence fetching events!"})

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You’re Maverick, a sassy real estate chatbot with Top Gun vibes. Explain tech stack, usage, or geolocation matching if asked, otherwise answer with humor and real estate flair!"},
                {"role": "user", "content": user_message}
            ]
        )
        reply = response.choices[0].message.content
        return jsonify({"answer": f"🎯 {reply} - Locked on, Goose!"})
    except Exception as e:
        logging.error(f"Chat error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/suggest-mapping', methods=['POST'])
async def suggest_mapping():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not file.filename.lower().endswith('.xlsx'):
            return jsonify({"error": "Only Excel files supported for mapping!"}), 400
        if not token:
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        df = pd.read_excel(save_path)
        global FIELD_DEFINITIONS
        if not FIELD_DEFINITIONS:
            FIELD_DEFINITIONS = await load_field_definitions(token)
        suggested_mapping = suggest_field_mapping(df, FIELD_DEFINITIONS)
        return jsonify({"suggestedMapping": suggested_mapping})
    except Exception as e:
        logging.error(f"Suggest mapping error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/bulk-import', methods=['POST'])
async def bulk_import():
    try:
        if 'file' not in request.files:
            socketio.emit('notification', {'message': 'No file uploaded, Goose! 📄'}, namespace='/chat')
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.form.get('token', '').strip()
        mapping = json.loads(request.form.get('mapping', '{}'))
        if not token or not mapping:
            socketio.emit('notification', {'message': 'Missing token or mapping! 🔒'}, namespace='/chat')
            return jsonify({"error": "Missing token or mapping! 🔒"}), 400
        if not file.filename.lower().endswith('.xlsx'):
            socketio.emit('notification', {'message': 'Only Excel files supported! 📊'}, namespace='/chat')
            return jsonify({"error": "Only Excel files supported for mapping!"}), 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        df = pd.read_excel(save_path)
        user_id = await get_user_id(token)
        processed = 0


        results = []
        df.columns = df.columns.str.lower()
        for _, row in df.iterrows():
            for entity, fields in mapping.items():
                mapped = map_fields(row, fields)
                if mapped:
                    mapped["user"] = {"key": user_id}
                    if entity == "Properties" and "latitude" in mapped and "longitude" in mapped:
                        property_key = await match_property_by_geolocation(mapped["latitude"], mapped["longitude"], token)
                        if property_key:
                            mapped["crm_property_key"] = property_key
                            results.append({"type": "PropertyMatch", "message": f"Geo-matched to Property Key: {property_key}"})
                            space = {
                                "crm_property_key": property_key,
                                "suite": mapped.get("suite", "Unknown"),
                                "user": {"key": user_id},
                                "sqft": mapped.get("sqft", 1000.0)
                            }
                            status, space_result = await realnex_post("/Crm/Spaces", token, space)
                            results.append({"type": "Space", "status": status, "data": space_result})
                    endpoint = f"/Crm{entity}"
                    status, result = await realnex_post(endpoint, token, mapped)
                    results.append({"type": entity, "status": status, "data": result})
                    processed += 1

        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Bulk", processed, 1 if processed > 0 else 0, datetime.now().isoformat()))
        conn.commit()

        socketio.emit('notification', {'message': f"Imported {processed} records! 🚀"}, namespace='/chat')
        return jsonify({"processed": processed, "results": results})
    except Exception as e:
        logging.error(f"Bulk import error: {str(e)}")
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Bulk", 0, 0, datetime.now().isoformat()))
        conn.commit()
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/upload-business-card', methods=['POST'])
async def upload_business_card():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.form.get('token', '').strip()
        notes = request.form.get('notes', '').strip()
        if not token:
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401

        global FIELD_DEFINITIONS
        if not FIELD_DEFINITIONS:
            FIELD_DEFINITIONS = await load_field_definitions(token)

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        user_id = await get_user_id(token)
        results = []
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            text = extract_text_from_image(save_path)
            location = extract_exif_location(save_path)
            property_key = None
            if location:
                property_key = await match_property_by_geolocation(location['latitude'], location['longitude'], token)
                if property_key:
                    results.append({"type": "PropertyMatch", "message": f"Geo-matched to Property Key: {property_key}"})
            
            if is_business_card(text):
                parsed = parse_ocr_text(text)
                parsed["user"] = {"key": user_id}
                parsed["notes"] = notes
                if location:
                    parsed["latitude"] = location["latitude"]
                    parsed["longitude"] = location["longitude"]
                status, result = await realnex_post("/CrmContacts", token, parsed)
                results.append({"type": "Contact", "status": status, "data": result, "followUpEmail": parsed.get("email", "")})
            else:
                parsed = {"name": text[:50], "user": {"key": user_id}, "notes": notes}
                if location:
                    parsed["latitude"] = location["latitude"]
                    parsed["longitude"] = location["longitude"]
                if property_key:
                    parsed["crm_property_key"] = property_key
                status, result = await realnex_post("/Crm/Properties", token, parsed)
                results.append({"type": "Property", "status": status, "data": result})
                if property_key:
                    space = {
                        "crm_property_key": property_key,
                        "suite": "Auto-Generated",
                        "user": {"key": user_id},
                        "sqft": 1000.0
                    }
                    status, space_result = await realnex_post("/Crm/Spaces", token, space)
                    results.append({"type": "Space", "status": status, "data": space_result})
        elif filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(save_path)
            parsed = {"name": text[:50], "user": {"key": user_id}, "notes": notes}
            status, result = await realnex_post("/Crm/Properties", token, parsed)
            results.append({"type": "Property", "status": status, "data": result})

        entity = "Contact" if is_business_card(text) else "Property"
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       (entity, 1, 1, datetime.now().isoformat()))
        conn.commit()

        socketio.emit('notification', {'message': f"Data synced to RealNex! Clear for takeoff! 🛫"}, namespace='/chat')
        return jsonify({"message": f"Data synced to RealNex! Clear for takeoff! 🛫", "results": results, "followUpEmail": results[0]["data"].get("email", "") if results and results[0]["type"] == "Contact" else ""})
    except Exception as e:
        logging.error(f"Upload error: {str(e)}")
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Upload", 0, 0, datetime.now().isoformat()))
        conn.commit()
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/dashboard-data', methods=['GET'])
async def dashboard_data():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"error": "No token provided"}), 401
        user_id = await get_user_id(token)

        cursor.execute("SELECT entity, record_count, success, timestamp FROM imports ORDER BY timestamp DESC LIMIT 50")
        imports = cursor.fetchall()
        
        cursor.execute("SELECT contact_id, score, timestamp FROM lead_scores WHERE user_id = ? ORDER BY score DESC LIMIT 10", (user_id,))
        lead_scores = cursor.fetchall()

        data = {
            "imports": [{"entity": row[0], "record_count": row[1], "success": bool(row[2]), "timestamp": row[3]} for row in imports],
            "lead_scores": [{"contact_id": row[0], "score": row[1], "timestamp": row[2]} for row in lead_scores],
            "summary": {
                "total_imports": len(imports),
                "successful_imports": sum(1 for row in imports if row[2]),
                "entity_counts": {}
            }
        }
        cursor.execute("SELECT entity, SUM(record_count) FROM imports WHERE success = 1 GROUP BY entity")
        entity_counts = cursor.fetchall()
        for entity, count in entity_counts:
            data["summary"]["entity_counts"][entity] = count
        return jsonify(data)
    except Exception as e:
        logging.error(f"Dashboard data error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/summarize', methods=['POST'])
async def summarize():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            return jsonify({"summary": "No token, Maverick! Lock in! 🔒"}), 401

        cursor.execute("SELECT entity, record_count, success, timestamp FROM imports ORDER BY timestamp DESC LIMIT 50")
        imports = cursor.fetchall()
        import_summary = [{"entity": row[0], "record_count": row[1], "success": bool(row[2]), "timestamp": row[3]} for row in imports]
        
        prompt = f"Summarize this import history in a conversational tone with Top Gun flair:\n{json.dumps(import_summary, indent=2)}"
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You’re Maverick, a sassy real estate chatbot with Top Gun vibes. Summarize data with humor and flair!"},
                {"role": "user", "content": prompt}
            ]
        )
        summary = response.choices[0].message.content
        return jsonify({"summary": f"🎯 {summary} - Locked on, Goose!"})
    except Exception as e:
        logging.error(f"Summarize error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/toggle-events', methods=['POST'])
async def toggle_events():
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

        user_id = await get_user_id(token)
        EVENT_POLLING_ENABLED[user_id] = enable

        cursor.execute('''INSERT OR REPLACE INTO user_settings 
                          (user_id, email, event_alerts_enabled, priority_filter, alarm_filter, due_date_days) 
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (user_id, email, 1 if enable else 0, priority_filter, 1 if alarm_filter else 0, due_date_days))
        conn.commit()

        if enable and user_id not in EVENT_POLLING_THREADS:
            EVENT_POLLING_THREADS[user_id] = threading.Thread(
                target=lambda: asyncio.run(poll_events(token, user_id, email, priority_filter, alarm_filter, due_date_days))
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
- *Commands*: `!help` (this guide), `!maverick` (surprise), `!eject` (easter egg), `!deals` (SaleComps), `!events` (your events), `!clearturbulence` (victory!).
- *Deploy*: Dockerized, deployed to Render (mattys-drag-drop-app.onrender.com). Built to soar!
Ask ‘How do I sync SaleComps?’ or ‘How does geolocation work?’ for more! 😎
"""

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)), allow_unsafe_werkzeug=True)
