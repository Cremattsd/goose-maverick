import json
import logging
import requests
import pandas as pd
from flask import Flask, request, jsonify, send_from_directory, g
from datetime import datetime, timedelta
from flask_cors import CORS
from tenacity import retry, stop_after_attempt, wait_exponential
from PIL import Image
import pytesseract
from openai import OpenAI
from goose_parser_tools import (
    extract_text_from_image,
    extract_text_from_pdf,
    extract_exif_location,
    is_business_card,
    parse_ocr_text,
    suggest_field_mapping,
    map_fields,
    auto_map_dataframe
)

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

UPLOAD_FOLDER = 'upload'
ERROR_LOG = 'errors.log'
CRM_DATA_FILE = 'scanned_data_points.json'
PROGRESS_FILE = 'upload_progress.json'
REMINDER_PREFS = 'reminder_settings.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
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

        return jsonify({"message": "Upload complete with OCR scan.", "ocrText": ocr_result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        with open(REMINDER_PREFS, 'w') as f:
            json.dump(data, f)
        return jsonify({"message": "Reminder preferences saved!"})
    except Exception as e:
        return jsonify({"error": f"Failed to save preferences: {str(e)}"}), 500

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
    try:
        data = request.json
        email = data.get("email")
        fname = data.get("firstName", "")
        lname = data.get("lastName", "")
        url = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0/lists/{MAILCHIMP_LIST_ID}/members"
        headers = {"Authorization": f"apikey {MAILCHIMP_API_KEY}"}
        payload = {
            "email_address": email,
            "status": "subscribed",
            "merge_fields": {"FNAME": fname, "LNAME": lname}
        }
        r = requests.post(url, headers=headers, json=payload)
        return jsonify({"status": r.status_code, "response": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sync-to-constant-contact', methods=['POST'])
def sync_constant_contact():
    try:
        data = request.json
        email = data.get("email")
        fname = data.get("firstName", "")
        lname = data.get("lastName", "")
        url = "https://api.cc.email/v3/contacts/sign_up_form"
        headers = {
            "Authorization": f"Bearer {CONSTANT_CONTACT_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "email_address": {"address": email},
            "first_name": fname,
            "last_name": lname,
            "list_memberships": [CONSTANT_CONTACT_LIST_ID]
        }
        r = requests.post(url, headers=headers, json=payload)
        return jsonify({"status": r.status_code, "response": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/zapier', methods=['POST'])
def zapier_webhook():
    payload = request.json
    logging.info(f"Zapier webhook received: {json.dumps(payload)}")
    token = os.getenv("REALNEX_TOKEN")
    if token and "email" in payload:
        try:
            contact = {
                "email": payload["email"],
                "first_name": payload.get("firstName", ""),
                "last_name": payload.get("lastName", ""),
                "company": payload.get("company", "")
            }
            realnex_post("/CrmContacts", token, contact)
        except Exception as e:
            logging.error(f"CRM Push failed: {str(e)}")
    return jsonify({"status": "received", "payload": payload})

@app.route('/goose/bulk-parse', methods=['POST'])
def goose_bulk_parse():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "CSV file required"}), 400
        file = request.files['file']
        df = pd.read_csv(file)
        mapped_data = auto_map_dataframe(df)
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        total = len(mapped_data)
        results = []
        for i, record in enumerate(mapped_data):
            try:
                code, res = realnex_post("/CrmContacts", token, record)
                results.append({"record": record, "status": code})
            except Exception as e:
                results.append({"record": record, "error": str(e)})
            with open(PROGRESS_FILE, 'w') as pf:
                json.dump({"current": i+1, "total": total}, pf)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/upload/progress', methods=['GET'])
def upload_progress():
    if not os.path.exists(PROGRESS_FILE):
        return jsonify({"current": 0, "total": 0})
    with open(PROGRESS_FILE, 'r') as f:
        return jsonify(json.load(f))



def requires_token(f):
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token or not token.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid token"}), 403
        token = token.split("Bearer ")[-1]
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.get(f"{REALNEX_API_BASE}/Me", headers=headers)
            if response.status_code != 200:
                return jsonify({"error": "Unauthorized"}), 403
            g.realnex_token = token
        except:
            return jsonify({"error": "Token validation failed"}), 403
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


@app.route('/field-map', methods=['GET'])
def field_map_ui():
    return send_from_directory('static', 'field-map.html')

@app.route('/api/properties', methods=['GET', 'POST', 'PUT', 'DELETE'])
def properties():
    if request.method == 'GET':
        return jsonify({"message": "List all properties (mocked)."})
    if request.method == 'POST':
        return jsonify({"message": "Property created (mocked)."})
    if request.method == 'PUT':
        return jsonify({"message": "Property updated (mocked)."})
    if request.method == 'DELETE':
        return jsonify({"message": "Property deleted (mocked)."})

@app.route('/api/spaces', methods=['GET', 'POST', 'PUT', 'DELETE'])
def spaces():
    if request.method == 'GET':
        return jsonify({"message": "List all spaces (mocked)."})
    if request.method == 'POST':
        return jsonify({"message": "Space created (mocked)."})
    if request.method == 'PUT':
        return jsonify({"message": "Space updated (mocked)."})
    if request.method == 'DELETE':
        return jsonify({"message": "Space deleted (mocked)."})

@app.route('/api/projects', methods=['GET', 'POST', 'PUT', 'DELETE'])
def projects():
    if request.method == 'GET':
        return jsonify({"message": "List all projects (mocked)."})
    if request.method == 'POST':
        return jsonify({"message": "Project created (mocked)."})
    if request.method == 'PUT':
        return jsonify({"message": "Project updated (mocked)."})
    if request.method == 'DELETE':
        return jsonify({"message": "Project deleted (mocked)."})

@app.route('/admin/users', methods=['GET'])
def admin_users():
    return jsonify({"users": ["admin@realnex.com", "user@realnex.com"]})

@app.route('/admin/logs', methods=['GET'])
def admin_logs():
    if not os.path.exists(ERROR_LOG): return jsonify([])
    with open(ERROR_LOG, 'r') as f:
        return jsonify({"logs": f.readlines()[-50:]})

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

from apscheduler.schedulers.background import BackgroundScheduler
scheduler = BackgroundScheduler()

def send_weekly_summary():
    if os.path.exists(CRM_DATA_FILE):
        one_week_ago = datetime.utcnow() - timedelta(days=7)
        with open(CRM_DATA_FILE, 'r') as f:
            records = json.load(f)
        recent = [r for r in records if datetime.fromisoformat(r['timestamp']) >= one_week_ago]
        logging.info(f"Weekly summary: {len(recent)} records")

scheduler.add_job(send_weekly_summary, 'interval', days=7)
scheduler.start()


@app.route('/field-map/save', methods=['POST'])
def save_field_mapping():
    try:
        data = request.json
        with open('saved_mapping.json', 'w') as f:
            json.dump(data, f, indent=2)
        return jsonify({"message": "Mapping saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/field-map/saved', methods=['GET'])
def load_field_mapping():
    try:
        if not os.path.exists('saved_mapping.json'):
            return jsonify({})
        with open('saved_mapping.json', 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/field-map/save/<map_name>', methods=['POST'])
def save_named_field_mapping(map_name):
    try:
        data = request.json
        file_name = f'saved_mapping_{map_name}.json'
        with open(file_name, 'w') as f:
            json.dump(data, f, indent=2)
        return jsonify({"message": f"Mapping '{map_name}' saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/field-map/saved/<map_name>', methods=['GET'])
def load_named_field_mapping(map_name):
    try:
        file_name = f'saved_mapping_{map_name}.json'
        if not os.path.exists(file_name):
            return jsonify({})
        with open(file_name, 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.before_request
def log_request_info():
    logging.info(f"{datetime.utcnow().isoformat()} - {request.method} {request.path} from {request.remote_addr}")

@app.route('/api/projects/<project_id>', methods=['GET'])
def get_project_by_id(project_id):
    return jsonify({"project_id": project_id, "message": "Project details (mocked)."})

@app.route('/api/spaces/<space_id>', methods=['GET'])
def get_space_by_id(space_id):
    return jsonify({"space_id": space_id, "message": "Space details (mocked)."})

@app.route('/api/properties/<property_id>', methods=['GET'])
def get_property_by_id(property_id):
    return jsonify({"property_id": property_id, "message": "Property details (mocked)."})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
