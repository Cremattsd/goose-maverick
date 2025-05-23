import json
import logging
import os
import httpx
import smtplib
import sqlite3
import redis
from email.mime.text import MIMEText
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import openai
import asyncio
import requests
from mailchimp_marketing import Client as MailchimpClient
from mailchimp_marketing.api_client import ApiClientError
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

# Redis for caching
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

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
    smtp_email TEXT,
    smtp_password TEXT,
    mailchimp_api_key TEXT,
    constant_contact_api_key TEXT,
    constant_contact_access_token TEXT,
    realnex_group TEXT,
    mailchimp_list_id TEXT,
    constant_contact_list_id TEXT,
    event_trigger_priority TEXT,
    event_trigger_alarm INTEGER
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

# HTTP client with connection pooling
http_client = httpx.AsyncClient(timeout=30.0)

# Event polling state
EVENT_POLLING_ENABLED = {}
EVENT_POLLING_THREADS = {}
LAST_EVENT_COUNT = {}
FIELD_DEFINITIONS = {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def load_field_definitions(token):
    global FIELD_DEFINITIONS
    cache_key = f"field_definitions:{token}"
    cached = redis_client.get(cache_key)
    if cached:
        FIELD_DEFINITIONS = json.loads(cached)
        return FIELD_DEFINITIONS

    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = await http_client.get(f"{REALNEX_API_BASE}/Crm/definitions", headers=headers)
        response.raise_for_status()
        tables = response.json()
        for table in tables:
            response = await http_client.get(f"{REALNEX_API_BASE}/Crm/definitions/{table}", headers=headers)
            response.raise_for_status()
            FIELD_DEFINITIONS[table] = response.json()
        redis_client.setex(cache_key, 3600, json.dumps(FIELD_DEFINITIONS))
    except Exception as e:
        logging.warning(f"API failed, loading realnex_fields.json: {str(e)}")
        with open("realnex_fields.json", "r") as f:
            FIELD_DEFINITIONS = json.load(f)
    return FIELD_DEFINITIONS

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    cache_key = f"post:{endpoint}:{token}:{json.dumps(data, sort_keys=True)}"
    cached = redis_client.get(cache_key)
    if cached:
        return 200, json.loads(cached)

    response = await http_client.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    response.raise_for_status()
    result = response.json() if response.content else {}
    redis_client.setex(cache_key, 300, json.dumps(result))
    return response.status_code, result

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def realnex_get(endpoint, token, is_odata=False):
    headers = {"Authorization": f"Bearer {token}"}
    base = ODATA_BASE if is_odata else REALNEX_API_BASE
    cache_key = f"get:{base}/{endpoint}:{token}"
    cached = redis_client.get(cache_key)
    if cached:
        return 200, json.loads(cached)

    response = await http_client.get(f"{base}/{endpoint}", headers=headers)
    response.raise_for_status()
    result = response.json().get('value', response.json())
    redis_client.setex(cache_key, 300, json.dumps(result))
    return response.status_code, result

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def get_user_id(token):
    headers = {"Authorization": f"Bearer {token}"}
    cache_key = f"user_id:{token}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached

    response = await http_client.get(f"{REALNEX_API_BASE}/Client?api-version=1.0", headers=headers)
    response.raise_for_status()
    user_id = response.json().get('key')
    redis_client.setex(cache_key, 3600, user_id)
    return user_id

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def match_property_by_geolocation(lat, lon, token):
    headers = {"Authorization": f"Bearer {token}"}
    query = f"Properties?$filter=latitude eq {lat} and longitude eq {lon}&$top=1"
    cache_key = f"geo:{lat}:{lon}:{token}"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached) if cached != "null" else None

    response = await http_client.get(f"{ODATA_BASE}/{query}", headers=headers)
    response.raise_for_status()
    properties = response.json().get('value', [])
    result = properties[0].get('crm_property_key') if properties else None
    redis_client.setex(cache_key, 300, json.dumps(result))
    return result

async def get_realnex_groups(token):
    try:
        status, groups = await realnex_get("Groups?$select=groupId,name", token, is_odata=True)
        if status == 200:
            return [{"id": g["groupId"], "name": g["name"]} for g in groups]
        return []
    except Exception as e:
        logging.error(f"Fetch RealNex groups error: {str(e)}")
        return []

async def get_mailchimp_lists(mailchimp_api_key):
    try:
        mailchimp = MailchimpClient()
        mailchimp.set_config({"api_key": mailchimp_api_key, "server": mailchimp_api_key.split('-')[-1]})
        lists = mailchimp.lists.get_all_lists().get('lists', [])
        return [{"id": lst["id"], "name": lst["name"]} for lst in lists]
    except ApiClientError as e:
        logging.error(f"Fetch Mailchimp lists error: {str(e)}")
        return []

async def get_constant_contact_lists(constant_contact_api_key, constant_contact_access_token):
    try:
        headers = {"Authorization": f"Bearer {constant_contact_access_token}", "Accept": "application/json"}
        response = requests.get(
            "https://api.cc.email/v3/contact_lists",
            headers=headers,
            params={"api_key": constant_contact_api_key}
        )
        response.raise_for_status()
        lists = response.json().get('lists', [])
        return [{"id": lst["list_id"], "name": lst["name"]} for lst in lists]
    except requests.RequestException as e:
        logging.error(f"Fetch Constant Contact lists error: {str(e)}")
        return []

def send_email_alert(subject, body, to_email, user_id):
    cursor.execute("SELECT smtp_email, smtp_password FROM user_settings WHERE user_id = ?", (user_id,))
    settings = cursor.fetchone()
    if not settings or not settings[0] or not settings[1]:
        logging.warning(f"No SMTP credentials for user {user_id}, falling back to WebSocket")
        socketio.emit('notification', {'message': f"{subject}: {body}"}, namespace='/chat')
        return

    smtp_email, smtp_password = settings
    smtp_server = "smtp.gmail.com" if smtp_email.endswith("@gmail.com") else "smtp-mail.outlook.com"
    smtp_port = 587

    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_email
        msg['To'] = to_email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_email, msg.as_string())
        logging.info(f"Email sent to {to_email} for user {user_id}")
    except Exception as e:
        logging.error(f"Email alert failed for user {user_id}: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Email alert failed! {str(e)}"}, namespace='/chat')

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
        Return a JSON list of {{"contact_id": "id", "score": score, "name": "name"}} entries.
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

        socketio.emit('lead_scores_updated', {'user_id': user_id, 'scores': scores}, namespace='/chat')
    except Exception as e:
        logging.error(f"Lead scoring error for user {user_id}: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Lead scoring failed! {str(e)}"}, namespace='/chat')

async def poll_events(token, user_id, email):
    global LAST_EVENT_COUNT
    LAST_EVENT_COUNT[user_id] = LAST_EVENT_COUNT.get(user_id, 0)
    cursor.execute("SELECT due_date_days, event_trigger_priority, event_trigger_alarm FROM user_settings WHERE user_id = ?", (user_id,))
    settings = cursor.fetchone()
    if not settings:
        logging.warning(f"No settings for user {user_id}")
        return
    due_date_days, trigger_priority, trigger_alarm = settings
    trigger_alarm = bool(trigger_alarm)

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
                priority_match = (trigger_priority.lower() == 'any' or event_priority.lower() == trigger_priority.lower())
                alarm_match = (not trigger_alarm or has_alarm)

                if due_soon and priority_match and alarm_match:
                    new_events.append(event)

            event_count = len(new_events)
            if event_count > LAST_EVENT_COUNT[user_id]:
                new_event_count = event_count - LAST_EVENT_COUNT[user_id]
                message = f"You've got {new_event_count} events due soon! 🛫 Check 'em out!"
                send_email_alert(
                    "RealNex Event Due Alert",
                    f"Maverick here! {message}\n\n{json.dumps(new_events[-new_event_count:], indent=2)}",
                    email,
                    user_id
                )
                LAST_EVENT_COUNT[user_id] = event_count

            await score_leads(token, user_id)
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Event polling error for user {user_id}: {str(e)}")
            socketio.emit('notification', {'message': f"Turbulence: Event polling failed! {str(e)}"}, namespace='/chat')
            await asyncio.sleep(300)

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/dashboard')
def dashboard():
    return send_from_directory('static/dashboard', 'index.html')

@app.route('/settings')
def settings():
    return send_from_directory('static', 'settings.html')

@app.route('/<path:path>')
def serve_static(path):
    try:
        return send_from_directory('static', path)
    except FileNotFoundError:
        logging.error(f"Static file not found: {path}")
        socketio.emit('notification', {'message': f"File {path} not found! Check the hangar, Goose! 📂"}, namespace='/chat')
        return jsonify({"error": f"File {path} not found! Check the hangar, Goose! 📂"}), 404

@app.route('/validate-token', methods=['POST'])
async def validate_token():
    try:
        token = request.json.get('token', '').strip()
        if not token:
            socketio.emit('notification', {'message': 'No token provided, Goose! 📄'}, namespace='/chat')
            return jsonify({"valid": False, "error": "No token provided"}), 400
        status, _ = await realnex_get("Client?api-version=1.0", token)
        return jsonify({"valid": status == 200})
    except Exception as e:
        logging.error(f"Token validation error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Token validation failed! {str(e)}"}, namespace='/chat')
        return jsonify({"valid": False, "error": str(e)}), 500

@app.route('/get-realnex-groups', methods=['GET'])
async def get_realnex_groups_route():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401
        groups = await get_realnex_groups(token)
        return jsonify({"groups": groups})
    except Exception as e:
        logging.error(f"Get RealNex groups error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Get groups failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/get-marketing-lists', methods=['GET'])
async def get_marketing_lists():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401
        user_id = await get_user_id(token)
        cursor.execute("SELECT mailchimp_api_key, constant_contact_api_key, constant_contact_access_token FROM user_settings WHERE user_id = ?", (user_id,))
        settings = cursor.fetchone()
        mailchimp_lists = []
        constant_contact_lists = []
        if settings:
            mailchimp_api_key, constant_contact_api_key, constant_contact_access_token = settings
            if mailchimp_api_key:
                mailchimp_lists = await get_mailchimp_lists(mailchimp_api_key)
            if constant_contact_api_key and constant_contact_access_token:
                constant_contact_lists = await get_constant_contact_lists(constant_contact_api_key, constant_contact_access_token)
        return jsonify({"mailchimp_lists": mailchimp_lists, "constant_contact_lists": constant_contact_lists})
    except Exception as e:
        logging.error(f"Get marketing lists error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Get lists failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/save-settings', methods=['POST'])
async def save_settings():
    try:
        data = request.json
        smtp_email = data.get('smtp_email', '').strip()
        smtp_password = data.get('smtp_password', '').strip()
        mailchimp_api_key = data.get('mailchimp_api_key', '').strip()
        constant_contact_api_key = data.get('constant_contact_api_key', '').strip()
        constant_contact_access_token = data.get('constant_contact_access_token', '').strip()
        realnex_group = data.get('realnex_group', '').strip()
        mailchimp_list_id = data.get('mailchimp_list_id', '').strip()
        constant_contact_list_id = data.get('constant_contact_list_id', '').strip()
        due_date_days = int(data.get('due_date_days', 7))
        event_trigger_priority = data.get('event_trigger_priority', 'any').strip().lower()
        event_trigger_alarm = data.get('event_trigger_alarm', False)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401

        user_id = await get_user_id(token)
        cursor.execute('''INSERT OR REPLACE INTO user_settings 
                          (user_id, smtp_email, smtp_password, mailchimp_api_key, constant_contact_api_key, 
                           constant_contact_access_token, realnex_group, mailchimp_list_id, constant_contact_list_id,
                           due_date_days, event_trigger_priority, event_trigger_alarm) 
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (user_id, smtp_email, smtp_password, mailchimp_api_key, constant_contact_api_key,
                        constant_contact_access_token, realnex_group, mailchimp_list_id, constant_contact_list_id,
                        due_date_days, event_trigger_priority, 1 if event_trigger_alarm else 0))
        conn.commit()
        socketio.emit('notification', {'message': 'Settings saved! Ready to sync and trigger alerts! 🔔'}, namespace='/chat')
        return jsonify({"message": "Settings saved! Ready to sync and trigger alerts! 🔔"})
    except Exception as e:
        logging.error(f"Save settings error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Save settings failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/sync-contacts', methods=['POST'])
async def sync_contacts():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401
        user_id = await get_user_id(token)
        cursor.execute("SELECT realnex_group, mailchimp_api_key, mailchimp_list_id, constant_contact_api_key, constant_contact_access_token, constant_contact_list_id FROM user_settings WHERE user_id = ?", (user_id,))
        settings = cursor.fetchone()
        if not settings or not settings[0]:
            socketio.emit('notification', {'message': 'No RealNex group selected! Visit Settings. ⚙️'}, namespace='/chat')
            return jsonify({"error": "No RealNex group selected! Visit Settings. ⚙️"}), 400

        realnex_group, mailchimp_api_key, mailchimp_list_id, constant_contact_api_key, constant_contact_access_token, constant_contact_list_id = settings
        status, contacts = await realnex_get(f"Contacts?$filter=groupId eq '{realnex_group}'&$top=50", token, is_odata=True)
        if status != 200:
            socketio.emit('notification', {'message': 'Turbulence fetching RealNex contacts!'}, namespace='/chat')
            return jsonify({"error": "Turbulence fetching RealNex contacts!"}), 500

        synced = 0
        results = []
        for contact in contacts:
            email = contact.get('email', '')
            if not email:
                continue
            contact_data = {
                "email_address": email,
                "first_name": contact.get('firstName', ''),
                "last_name": contact.get('lastName', ''),
                "status": "subscribed"
            }

            if mailchimp_api_key and mailchimp_list_id:
                try:
                    mailchimp = MailchimpClient()
                    mailchimp.set_config({"api_key": mailchimp_api_key, "server": mailchimp_api_key.split('-')[-1]})
                    mailchimp.lists.add_list_member(mailchimp_list_id, contact_data)
                    results.append({"type": "Mailchimp", "status": 200, "email": email})
                    synced += 1
                except ApiClientError as e:
                    logging.error(f"Mailchimp sync error for {email}: {str(e)}")
                    results.append({"type": "Mailchimp", "status": 500, "email": email, "error": str(e)})

            if constant_contact_api_key and constant_contact_access_token and constant_contact_list_id:
                try:
                    headers = {"Authorization": f"Bearer {constant_contact_access_token}", "Accept": "application/json"}
                    cc_contact = {
                        "email_address": {"address": email, "permission_to_send": "implicit"},
                        "first_name": contact.get('firstName', ''),
                        "last_name": contact.get('lastName', ''),
                        "list_memberships": [constant_contact_list_id]
                    }
                    response = requests.post(
                        "https://api.cc.email/v3/contacts",
                        headers=headers,
                        json=cc_contact,
                        params={"api_key": constant_contact_api_key}
                    )
                    response.raise_for_status()
                    results.append({"type": "ConstantContact", "status": 201, "email": email})
                    synced += 1
                except requests.RequestException as e:
                    logging.error(f"Constant Contact sync error for {email}: {str(e)}")
                    results.append({"type": "ConstantContact", "status": 500, "email": email, "error": str(e)})

        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Sync", synced, 1 if synced > 0 else 0, datetime.now().isoformat()))
        conn.commit()

        socketio.emit('notification', {'message': f"Synced {synced} contacts to marketing lists! 🚀"}, namespace='/chat')
        return jsonify({"synced": synced, "results": results})
    except Exception as e:
        logging.error(f"Sync contacts error: {str(e)}")
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Sync", 0, 0, datetime.now().isoformat()))
        conn.commit()
        socketio.emit('notification', {'message': f"Turbulence: Sync failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/transcribe', methods=['POST'])
async def transcribe():
    try:
        transcription = request.json.get('transcription', '').strip().lower()
        if not transcription:
            socketio.emit('notification', {'message': 'No transcription provided, Goose! 🎙️'}, namespace='/chat')
            return jsonify({"error": "No transcription provided"}), 400

        if transcription == "!help" or "tech stack" in transcription or "how to use" in transcription:
            return jsonify({"answer": HELP_MESSAGE})
        if transcription == "!maverick":
            return jsonify({"answer": "I feel the need… the need for leads! 🛩️ https://media.giphy.com/media/3o7aDcz7XVeM6fW8zC/giphy.gif"})
        if transcription == "!eject":
            return jsonify({"answer": "Eject, eject, eject! Goose is outta here! 🪂 https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"})
        if transcription == "!clearturbulence":
            return jsonify({"answer": "Turbulence cleared! Skies are blue, Goose! 🛫 https://media.giphy.com/media/3o7TKsQ8vXh8lTJyZw/giphy.gif"})
        if transcription == "!deals":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            status, deals = await realnex_get("SaleComps?$top=3", token, is_odata=True)
            return jsonify({"answer": f"Latest deals: {json.dumps(deals, indent=2)}" if status == 200 else "Turbulence fetching deals!"})
        if transcription == "!events":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            user_id = await get_user_id(token)
            status, events = await realnex_get(f"Events?$filter=userId eq {user_id}&$top=5", token, is_odata=True)
            return jsonify({"answer": f"Your events: {json.dumps(events, indent=2)}" if status == 200 else "Turbulence fetching events!"})

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You’re Maverick, a sassy real estate chatbot with Top Gun vibes. Explain tech stack, usage, or geolocation matching if asked, otherwise answer with humor and real estate flair!"},
                {"role": "user", "content": transcription}
            ]
        )
        reply = response.choices[0].message.content
        socketio.emit('notification', {'message': f"Voice command processed: {transcription}"}, namespace='/chat')
        return jsonify({"answer": f"🎯 {reply} - Locked on, Goose!"})
    except Exception as e:
        logging.error(f"Transcription error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Transcription error! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/ask', methods=['POST'])
async def ask():
    try:
        user_message = request.json.get("message", "").strip().lower()
        if not user_message:
            socketio.emit('notification', {'message': 'Gimme something to work with, Goose! 😎'}, namespace='/chat')
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
                socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            status, deals = await realnex_get("SaleComps?$top=3", token, is_odata=True)
            return jsonify({"answer": f"Latest deals: {json.dumps(deals, indent=2)}" if status == 200 else "Turbulence fetching deals!"})
        if user_message == "!events":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            user_id = await get_user_id(token)
            status, events = await realnex_get(f"Events?$filter=userId eq {user_id}&$top=5", token, is_odata=True)
            return jsonify({"answer": f"Your events: {json.dumps(events, indent=2)}" if status == 200 else "Turbulence fetching events!"})

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You’re Maverick, a sassy real estate chatbot with Top Gun vibes. Explain tech stack, usage, or geolocation matching if asked, otherwise answer with humor and real estate flair!"},
                {"role": "user", "content": user_message}
            ]
        )
        reply = response.choices[0].message.content
        socketio.emit('notification', {'message': f"Command processed: {user_message}"}, namespace='/chat')
        return jsonify({"answer": f"🎯 {reply} - Locked on, Goose!"})
    except Exception as e:
        logging.error(f"Chat error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Chat error! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/suggest-mapping', methods=['POST'])
async def suggest_mapping():
    try:
        if 'file' not in request.files:
            socketio.emit('notification', {'message': 'No file uploaded, Goose! 📄'}, namespace='/chat')
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not file.filename.lower().endswith('.xlsx'):
            socketio.emit('notification', {'message': 'Only Excel files supported! 📊'}, namespace='/chat')
            return jsonify({"error": "Only Excel files supported for mapping!"}), 400
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
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
        socketio.emit('notification', {'message': f"Turbulence: Mapping error! {str(e)}"}, namespace='/chat')
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
        socketio.emit('notification', {'message': f"Turbulence: Bulk import failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/upload-business-card', methods=['POST'])
async def upload_business_card():
    try:
        if 'file' not in request.files:
            socketio.emit('notification', {'message': 'No file uploaded, Goose! 📄'}, namespace='/chat')
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.form.get('token', '').strip()
        notes = request.form.get('notes', '').strip()
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"error": "No token, Maverick! Lock in! 🔒"}), 401

        global FIELD_DEFINITIONS
        if not FIELD_DEFINITIONS:
            FIELD_DEFINITIONS = await load_field_definitions(token)

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        user_id = await get_user_id(token)
        results = []
        text = None
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

        entity = "Contact" if text and is_business_card(text) else "Property"
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       (entity, 1, 1, datetime.now().isoformat()))
        conn.commit()

        socketio.emit('notification', {'message': f"Data synced to RealNex! Clear for takeoff! 🛫"}, namespace='/chat')
        return jsonify({
            "message": f"Data synced to RealNex! Clear for takeoff! 🛫",
            "results": results,
            "followUpEmail": results[0]["data"].get("email", "") if results and results[0]["type"] == "Contact" else ""
        })
    except Exception as e:
        logging.error(f"Upload error: {str(e)}")
        cursor.execute("INSERT INTO imports (entity, record_count, success, timestamp) VALUES (?, ?, ?, ?)",
                       ("Upload", 0, 0, datetime.now().isoformat()))
        conn.commit()
        socketio.emit('notification', {'message': f"Turbulence: Upload failed! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/dashboard-data', methods=['GET'])
async def dashboard_data():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token provided, Maverick! 🔒'}, namespace='/chat')
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
        socketio.emit('notification', {'message': f"Turbulence: Dashboard data error! {str(e)}"}, namespace='/chat')
        return jsonify({"error": str(e)}), 500

@app.route('/summarize', methods=['POST'])
async def summarize():
    try:
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
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
        socketio.emit('notification', {'message': 'Summary generated! 📊'}, namespace='/chat')
        return jsonify({"summary": f"🎯 {summary} - Locked on, Goose!"})
    except Exception as e:
        logging.error(f"Summarize error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Summarize error! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/toggle-events', methods=['POST'])
async def toggle_events():
    global EVENT_POLLING_ENABLED, EVENT_POLLING_THREADS
    try:
        data = request.json
        enable = data.get('enable', False)
        email = data.get('email', '').strip()
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            socketio.emit('notification', {'message': 'No token, Maverick! Lock in! 🔒'}, namespace='/chat')
            return jsonify({"message": "No token, Maverick! Lock in! 🔒"}), 401
        if not email:
            socketio.emit('notification', {'message': 'No email provided for alerts! 📧'}, namespace='/chat')
            return jsonify({"message": "No email provided for alerts! 📧"}), 400

        user_id = await get_user_id(token)
        if enable:
            cursor.execute("SELECT smtp_email, smtp_password, event_trigger_priority, event_trigger_alarm FROM user_settings WHERE user_id = ?", (user_id,))
            settings = cursor.fetchone()
            if not settings or not settings[0] or not settings[1]:
                socketio.emit('notification', {'message': 'No SMTP credentials set! Visit Settings to configure. ⚙️'}, namespace='/chat')
                return jsonify({"error": "No SMTP credentials set! Visit Settings to configure. ⚙️"}), 400
            if not settings[2] and not settings[3]:
                socketio.emit('notification', {'message': 'No event triggers set! Configure priority or alarm in Settings. ⚙️'}, namespace='/chat')
                return jsonify({"error": "No event triggers set! Configure priority or alarm in Settings. ⚙️"}), 400

        EVENT_POLLING_ENABLED[user_id] = enable
        cursor.execute('''INSERT OR REPLACE INTO user_settings 
                          (user_id, email, event_alerts_enabled) 
                          VALUES (?, ?, ?)''',
                       (user_id, email, 1 if enable else 0))
        conn.commit()

        if enable and user_id not in EVENT_POLLING_THREADS:
            EVENT_POLLING_THREADS[user_id] = threading.Thread(
                target=lambda: asyncio.run(poll_events(token, user_id, email))
            )
            EVENT_POLLING_THREADS[user_id].daemon = True
            EVENT_POLLING_THREADS[user_id].start()
            socketio.emit('notification', {'message': f"Event alerts enabled! Triggered alerts will fire to {email}. 🔔"}, namespace='/chat')
            return jsonify({"message": f"Event alerts enabled! Triggered alerts will fire to {email}. 🔔"})
        elif not enable and user_id in EVENT_POLLING_THREADS:
            EVENT_POLLING_ENABLED[user_id] = False
            EVENT_POLLING_THREADS.pop(user_id, None)
            socketio.emit('notification', {'message': 'Event alerts disabled. Radar off! 📡'}, namespace='/chat')
            return jsonify({"message": "Event alerts disabled. Radar off! 📡"})
        else:
            socketio.emit('notification', {'message': f"Event alerts already {'enabled' if enable else 'disabled'}!"}, namespace='/chat')
            return jsonify({"message": f"Event alerts already {'enabled' if enable else 'disabled'}!"})
    except Exception as e:
        logging.error(f"Toggle events error: {str(e)}")
        socketio.emit('notification', {'message': f"Turbulence: Toggle events error! {str(e)}"}, namespace='/chat')
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

HELP_MESSAGE = """
🎯 *Goose-Maverick: Tech Stack & Usage Guide* 🎯
- *Backend*: Flask (Python) with async httpx powers API routes (/ask, /upload-business-card, /bulk-import). Jet engine, bro!
- *Frontend*: Tailwind CSS for slick styling, Chart.js for dope dashboards, vanilla JS for drag-and-drop and voice input. Cockpit vibes!
- *Parsing*: Goose uses pandas for Excel, pytesseract/pdf2image/Pillow for OCR, exifread for geolocation. Radar locked!
- *APIs*: RealNex V1 OData (/CrmOData) fetches user IDs and events; non-OData (/CrmContacts) syncs data. OpenAI (GPT-4o) runs chat, summaries, and lead scoring, ready for Grok 3!
- *Caching*: Redis for lightning-fast API and field definition access.
- *Field Matching*: Pulls schemas from /api/v1/Crm/definitions or realnex_fields.json (4000+ fields!) to auto-match Contacts, Properties, Spaces, SaleComps.
- *Geolocation*: Photos’ EXIF data matches Properties/Spaces via latitude/longitude in OData queries.
- *Integrations*: Sync RealNex contacts to Mailchimp/Constant Contact lists via /sync-contacts, configured in /settings.
- *New Features*: 
  - Dashboard at /dashboard shows import stats and AI-powered lead scores with Chart.js!
  - Event triggers in /settings: set priority (e.g., High) or alarm to get emailed when events are due (SMTP or WebSocket).
  - Real-time notifications in the chat widget via WebSocket!
  - Voice-to-text input via /transcribe for hands-free commands!
  - Sync contacts to Mailchimp/Constant Contact with “Sync Now” button.
- *Usage*:
  1. Switch to Goose mode, enter your RealNex Bearer token (from RealNex dashboard).
  2. Visit /settings to configure SMTP email/password, Mailchimp/Constant Contact API keys, RealNex group, marketing lists, and event triggers (priority, alarm, due date days).
  3. Drag-and-drop photos (.png, .jpg), PDFs, or Excel (.xlsx) into the chat widget.
  4. For photos/PDFs, add notes and sync as Contacts or Properties. Photos geo-match to Properties/Spaces.
  5. For Excel, review/edit suggested field mappings, then import.
  6. Chat with Maverick via text or voice for help, CRM queries (‘Show my events’), or commands like `!maverick`!
  7. Visit /dashboard to see import stats, lead scores, and request a summary.
  8. Toggle event polling in Goose mode for alerts, with triggers set in /settings.
  9. Click “Sync Now” to push RealNex contacts to Mailchimp/Constant Contact.
- *Commands*: `!help` (this guide), `!maverick` (surprise), `!eject` (easter egg), `!deals` (SaleComps), `!events` (your events), `!clearturbulence` (victory!).
- *Deploy*: Dockerized, deployed to Render (mattys-drag-drop-app.onrender.com). Built to soar!
Ask ‘How do I sync SaleComps?’ or ‘How does geolocation work?’ for more! 😎
"""

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)), allow_unsafe_werkzeug=True)
