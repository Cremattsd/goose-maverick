# goose_maverick_backend.py – Full AI Sync System

import os
import json
import pytesseract
import requests
import exifread
from PIL import Image
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

geolocator = Nominatim(user_agent="realnex_goose")
REALNEX_API_BASE = "https://sync.realnex.com/api/v1"
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"

# === Helper: Post to RealNex ===
def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    return response.status_code, response.json() if response.content else {}

# === Helper: Get from OData ===
def realnex_get(endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
    return response.status_code, response.json().get('value', []) if response.ok else []

# === History Logger ===
def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    return realnex_post("/Crm/history", token, payload)

# === OCR Functions ===
def extract_text_from_image(image_path):
    return pytesseract.image_to_string(Image.open(image_path))

def extract_exif_location(image_path):
    with open(image_path, 'rb') as f:
        tags = exifread.process_file(f)
    def _deg(v):
        d, m, s = v.values
        return d.num/d.den + m.num/m.den/60 + s.num/s.den/3600
    if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
        lat, lon = _deg(tags['GPS GPSLatitude']), _deg(tags['GPS GPSLongitude'])
        if tags['GPS GPSLatitudeRef'].values != 'N': lat = -lat
        if tags['GPS GPSLongitudeRef'].values != 'E': lon = -lon
        location = geolocator.reverse((lat, lon), exactly_one=True)
        return {"lat": lat, "lon": lon, "address": location.address if location else None}
    return None

def is_business_card(text):
    return "@" in text and any(c.isdigit() for c in text) and any(len(line.split()) >= 2 for line in text.splitlines())

@app.route('/upload-business-card', methods=['POST'])
def upload_card():
    token = request.form.get('token')
    notes = request.form.get('notes', '')
    if 'file' not in request.files or not token:
        return jsonify({"error": "Missing file or token"}), 400

    file = request.files['file']
    path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(path)
    text = extract_text_from_image(path)
    exif = extract_exif_location(path)
    lines = text.splitlines()
    name = next((l for l in lines if len(l.split()) >= 2), "")
    email = next((l for l in lines if "@" in l), "")
    phone = next((l for l in lines if any(c.isdigit() for c in l) and '-' in l), "")

    contact = {"fullName": name.strip(), "email": email.strip(), "work": phone.strip(), "prospect": True}
    if is_business_card(text) and notes:
        contact["notes"] = notes.strip()

    status, result = realnex_post("/Crm/contact", token, contact)
    key = result.get("key")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"Imported via Goose\n\nOCR:\n{text}\n\nNotes:\n{notes}"
    create_history(token, "Goose Import", msg, key)

    draft = f"Subject: Great connecting!\n\nHi {name.split()[0] if name else 'there'},\n\nAdded you to my CRM — let me know how I can help.\n\nBest,\nMatty"
    return jsonify({"ocrText": text, "location": exif, "contactCreated": result, "status": status, "followUpEmail": draft})

# === GET CONTACTS + LAST ACTIVITY ===
@app.route('/sync-followups', methods=['POST'])
def sync_followups():
    token = request.json.get('token')
    days = int(request.json.get('days', 30))
    contacts = realnex_get("Contacts", token)
    cutoff = datetime.now() - timedelta(days=days)
    stale = [c for c in contacts if not c.get('lastActivity') or datetime.fromisoformat(c['lastActivity']) < cutoff]

    # Create or verify Follow Up Group
    group_resp = realnex_post("/Crm/contactgroup", token, {"name": "Follow Up Group"})
    group_id = group_resp[1].get("key") if group_resp[0] in [200, 201] else None

    # Add members
    for c in stale:
        realnex_post("/Crm/contactgroupmember", token, {"contact_key": c['Key'], "group_key": group_id})

    return jsonify({"matched": len(stale), "group_key": group_id})

# === SYNC TO MAILCHIMP ===
@app.route('/sync-mailchimp', methods=['POST'])
def sync_mailchimp():
    api_key = request.json.get("api_key")
    audience_id = request.json.get("audience_id")
    token = request.json.get("token")
    contacts = realnex_get("Contacts", token)

    for c in contacts:
        payload = {
            "email_address": c['Email'],
            "status": "subscribed",
            "merge_fields": {
                "FNAME": c.get("FirstName", ""),
                "LNAME": c.get("LastName", "")
            }
        }
        member_id = c['Email'].lower()
        url = f"https://usX.api.mailchimp.com/3.0/lists/{audience_id}/members"
        headers = {"Authorization": f"apikey {api_key}"}
        requests.post(url, headers=headers, json=payload)

    return jsonify({"synced": len(contacts)})

# === SYNC TO CONSTANT CONTACT ===
@app.route('/sync-constantcontact', methods=['POST'])
def sync_constant():
    api_key = request.json.get("api_key")
    token = request.json.get("access_token")
    list_id = request.json.get("list_id")
    crm_token = request.json.get("token")
    contacts = realnex_get("Contacts", crm_token)

    for c in contacts:
        contact = {
            "email_address": {"address": c['Email']},
            "first_name": c.get("FirstName", ""),
            "last_name": c.get("LastName", ""),
            "list_memberships": [list_id]
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        requests.post("https://api.cc.email/v3/contacts/sign_up_form", headers=headers, json=contact)

    return jsonify({"synced": len(contacts)})

# === AI Knowledge Base ===
with open("knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

@app.route('/ask', methods=['POST'])
def ask():
    msg = request.get_json().get("message", "").lower()
    for q, a in knowledge_base.items():
        if msg in q.lower():
            return jsonify({"answer": a})
    return jsonify({"answer": "Try rephrasing that, I didn’t find an answer."})

@app.route('/')
def home():
    return '✅ Goose Prime + Maverick AI are online — /static/index.html ready.'

if __name__ == '__main__':
    app.run(debug=True)
