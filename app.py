import os 
import json
import logging
import requests
import pandas as pd
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import (
    extract_text_from_image,
    extract_text_from_pdf,
    extract_exif_location,
    is_business_card,
    parse_ocr_text,
    suggest_field_mapping,
    map_fields
)
from PIL import Image
import pytesseract

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
ERROR_LOG = 'errors.log'
CRM_DATA_FILE = 'scanned_data_points.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")

CONSTANT_CONTACT_API_KEY = os.getenv("CONSTANT_CONTACT_API_KEY")
CONSTANT_CONTACT_ACCESS_TOKEN = os.getenv("CONSTANT_CONTACT_ACCESS_TOKEN")
CONSTANT_CONTACT_LIST_ID = os.getenv("CONSTANT_CONTACT_LIST_ID")

DEFAULT_CAMPAIGN_MODE = os.getenv("DEFAULT_CAMPAIGN_MODE", "realnex")
UNLOCK_EMAIL_PROVIDER_SELECTION = os.getenv("UNLOCK_EMAIL_PROVIDER_SELECTION", "false").lower() == "true"

DASHBOARD_PHRASES = [
    "show me the dashboard", "open the dashboard", "dashboard please",
    "launch dashboard", "give me an update", "open goose dashboard",
    "pull my metrics", "sync update", "how are my stats", "check my data"
]

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    response.raise_for_status()
    return response.status_code, response.json() if response.content else {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_get(endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.status_code, response.json().get('value', [])

def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    return realnex_post("/Crm/history", token, payload)

def sync_to_mailchimp(email, first_name="", last_name=""):
    try:
        url = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0/lists/{MAILCHIMP_LIST_ID}/members"
        data = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {"FNAME": first_name, "LNAME": last_name}
        }
        headers = {"Authorization": f"Bearer {MAILCHIMP_API_KEY}", "Content-Type": "application/json"}
        requests.post(url, headers=headers, json=data).raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Mailchimp sync failed: {str(e)}")
        return False

def sync_to_constant_contact(email, first_name="", last_name=""):
    try:
        headers = {
            "Authorization": f"Bearer {CONSTANT_CONTACT_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = {
            "email_address": {"address": email},
            "first_name": first_name,
            "last_name": last_name,
            "list_memberships": [CONSTANT_CONTACT_LIST_ID]
        }
        url = "https://api.cc.email/v3/contacts/sign_up_form"
        requests.post(url, headers=headers, json=data).raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Constant Contact sync failed: {str(e)}")
        return False

def sync_contact(email, first_name, last_name, provider=None):
    provider = provider or DEFAULT_CAMPAIGN_MODE
    if not UNLOCK_EMAIL_PROVIDER_SELECTION:
        provider = DEFAULT_CAMPAIGN_MODE
    if provider == "mailchimp":
        return sync_to_mailchimp(email, first_name, last_name)
    elif provider == "constant_contact":
        return sync_to_constant_contact(email, first_name, last_name)
    logging.info(f"Using internal RealNex campaign sync for {email}")
    return True

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip().lower()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        if any(phrase in user_message for phrase in DASHBOARD_PHRASES):
            return jsonify({"action": "show_dashboard", "message": "Pulling up your Goose Sync Dashboard now 📊"})

        if "who made you" in user_message or "who built you" in user_message:
            return jsonify({"answer": "I was made by Matty Boy — the mind behind Goose, Maverick, and the RealNex AI revolution."})

        if "help" in user_message or "what can you do" in user_message:
            return jsonify({"answer": "RealNex, RealNex Webinars, Real Blasts, or more — ask away!"})

        response = openai_client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": "You are a commercial real estate assistant. Only answer questions related to RealNex, RealNex VR, Pix-Virtual, or ViewLabs."},
                {"role": "user", "content": user_message}
            ]
        )

        answer = response.choices[0].message.content
        logging.info(f"User asked: {user_message}, Answered: {answer}")
        return jsonify({"answer": answer})
    except Exception as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500

@app.route('/upload', methods=['POST'])
def upload():
    try:
        file = request.files['file']
        filename = file.filename
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(save_path)

        ocr_result = ""
        if filename.lower().endswith(('png', 'jpg', 'jpeg')):
            image = Image.open(save_path)
            ocr_result = pytesseract.image_to_string(image).strip()

            if not os.path.exists(CRM_DATA_FILE):
                with open(CRM_DATA_FILE, 'w') as f:
                    json.dump([], f)

            with open(CRM_DATA_FILE, 'r+') as f:
                data = json.load(f)
                data.append({"timestamp": datetime.utcnow().isoformat(), "filename": filename, "text": ocr_result})
                f.seek(0)
                json.dump(data, f, indent=2)
                f.truncate()

        return jsonify({"message": "Upload complete with OCR scan and CRM sync.", "ocrText": ocr_result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/stats')
def dashboard_stats():
    try:
        files = os.listdir(UPLOAD_FOLDER)
        latest = max([os.path.getmtime(os.path.join(UPLOAD_FOLDER, f)) for f in files], default=0)
        with open(CRM_DATA_FILE, 'r') as f:
            records = json.load(f)
        return jsonify({"filesUploaded": len(files), "lastUploadTime": datetime.fromtimestamp(latest).isoformat() if latest else "N/A", "scannedPoints": len(records)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/errors')
def dashboard_errors():
    try:
        if not os.path.exists(ERROR_LOG): return jsonify({"errors": []})
        with open(ERROR_LOG, 'r') as f:
            return jsonify({"errors": f.readlines()[-10:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/data')
def dashboard_data():
    try:
        if not os.path.exists(CRM_DATA_FILE): return jsonify([])
        with open(CRM_DATA_FILE, 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/weekly-summary')
def dashboard_weekly_summary():
    try:
        if not os.path.exists(CRM_DATA_FILE): return jsonify([])
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        with open(CRM_DATA_FILE, 'r') as f:
            records = json.load(f)
        recent = [r for r in records if datetime.fromisoformat(r['timestamp']) >= one_week_ago]
        return jsonify(recent)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/dashboard/clean-old')
def clean_old_records():
    try:
        if not os.path.exists(CRM_DATA_FILE): return jsonify({"message": "Nothing to clean."})
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        with open(CRM_DATA_FILE, 'r+') as f:
            records = json.load(f)
            filtered = [r for r in records if datetime.fromisoformat(r['timestamp']) >= thirty_days_ago]
            f.seek(0)
            json.dump(filtered, f, indent=2)
            f.truncate()
        return jsonify({"message": f"Cleaned. {len(records) - len(filtered)} old records removed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/set-reminder-prefs', methods=['POST'])
def set_reminder_prefs():
    try:
        data = request.json
        with open('reminder_settings.json', 'w') as f:
            json.dump(data, f)
        return jsonify({"message": "Reminder preferences saved!"})
    except Exception as e:
        return jsonify({"error": f"Failed to save preferences: {str(e)}"}), 500

@app.route('/generate-email', methods=['POST'])
def generate_email():
    try:
        data = request.json
        parsed_data = data.get('summary', '')
        prompt = f'Write a professional follow-up email based on this data: {parsed_data}'
        response = openai_client.chat.completions.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': 'You are a commercial real estate assistant.'},
                {'role': 'user', 'content': prompt}
            ]
        )
        return jsonify({ 'email': response.choices[0].message.content })
    except Exception as e:
        return jsonify({ 'error': str(e) }), 500

@app.route('/validate-token', methods=['POST'])
def validate_token():
    try:
        token = request.json.get("token", "").strip()
        if not token:
            return jsonify({"error": "Token is required"}), 400

        status, result = realnex_get("Contacts?$top=1", token)
        if status == 200:
            return jsonify({"valid": True})
        return jsonify({"valid": False, "error": result.get("error", "Invalid token")}), 401
    except Exception as e:
        logging.error(f"Error validating token: {str(e)}")
        return jsonify({"error": f"Error validating token: {str(e)}"}), 500

@app.route('/terms', methods=['GET'])
def get_terms():
    return jsonify({
        "text": (
            "Protection of data is paramount to RealNex. By using the RealNex Services, you agree to abide by the Terms of Use. "
            "You represent that you are the owner of all data uploaded and have legal authority to upload it."
        )
    })

@app.route('/sync-to-mailchimp', methods=['POST'])
def sync_mailchimp():
    data = request.json
    success = sync_to_mailchimp(data.get("email"), data.get("firstName", ""), data.get("lastName", ""))
    return jsonify({"success": success})

@app.route('/sync-to-constant-contact', methods=['POST'])
def sync_constant_contact():
    data = request.json
    success = sync_to_constant_contact(data.get("email"), data.get("firstName", ""), data.get("lastName", ""))
    return jsonify({"success": success})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
