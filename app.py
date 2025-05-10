# goose_backend_upgrade.py

import os
import json
import pytesseract
import requests
import exifread
from PIL import Image
from geopy.geocoders import Nominatim
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

geolocator = Nominatim(user_agent="realnex_goose")
REALNEX_API_BASE = "https://sync.realnex.com/api/v1"

# === OCR & Location Extraction ===
def extract_text_from_image(image_path):
    image = Image.open(image_path)
    return pytesseract.image_to_string(image)

def extract_exif_location(image_path):
    with open(image_path, 'rb') as f:
        tags = exifread.process_file(f)

    def _convert_to_degrees(value):
        d, m, s = value.values
        return d.num / d.den + m.num / m.den / 60 + s.num / s.den / 3600

    if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
        lat = _convert_to_degrees(tags['GPS GPSLatitude'])
        lon = _convert_to_degrees(tags['GPS GPSLongitude'])
        if tags['GPS GPSLatitudeRef'].values != 'N':
            lat = -lat
        if tags['GPS GPSLongitudeRef'].values != 'E':
            lon = -lon
        location = geolocator.reverse((lat, lon), exactly_one=True)
        return {"lat": lat, "lon": lon, "address": location.address if location else None}
    return None

# === API Helpers ===
def realnex_post(endpoint, token, data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"{REALNEX_API_BASE}{endpoint}"
    response = requests.post(url, headers=headers, json=data)
    return response.status_code, response.json() if response.content else {}

def create_history(token, subject, notes, contact_key=None):
    data = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead",
    }
    if contact_key:
        data["contact_key"] = contact_key
    return realnex_post("/Crm/history", token, data)

# === Upload Endpoint ===
@app.route('/upload-business-card', methods=['POST'])
def upload_business_card():
    token = request.form.get('token')
    notes = request.form.get('notes', '')
    if 'file' not in request.files or not token:
        return jsonify({"error": "File and token required"}), 400

    file = request.files['file']
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    ocr_text = extract_text_from_image(filepath)
    exif_data = extract_exif_location(filepath)

    lines = ocr_text.splitlines()
    name = next((line for line in lines if len(line.split()) >= 2), "")
    email = next((line for line in lines if "@" in line), "")
    phone = next((line for line in lines if any(c.isdigit() for c in line) and '-' in line), "")

    contact_payload = {
        "fullName": name.strip(),
        "email": email.strip(),
        "work": phone.strip(),
        "prospect": True,
        "notes": notes.strip()
    }

    status, contact_response = realnex_post("/Crm/contact", token, contact_payload)
    contact_key = contact_response.get("key")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    history_note = f"Imported via Goose on {timestamp}\n\nOCR Text:\n{ocr_text}\n\nUser Notes:\n{notes}"
    create_history(token, subject="Goose Import Log", notes=history_note, contact_key=contact_key)

    first_name = name.split()[0] if name else "there"
    email_draft = f"""Subject: Great connecting today!

Hi {first_name},

It was a pleasure meeting you. I’ve added your info to my CRM and will follow up soon.

If there’s anything I can assist with — finding space, investment insights, or scheduling a tour — just let me know!

Best,  
Matty
"""

    # Log for email report
    import_log = {
        "file": filename,
        "created": [
            f"Contact: {name.strip()}"
        ],
        "matched": [],
        "notes": notes,
        "ocr": ocr_text,
        "timestamp": timestamp
    }

    return jsonify({
        "ocrText": ocr_text,
        "location": exif_data,
        "contactCreated": contact_response,
        "status": status,
        "followUpEmail": email_draft,
        "importLog": import_log
    })

# === Maverick Chat ===
with open("knowledge_base.json", "r") as f:
    knowledge_base = json.load(f)

@app.route('/ask', methods=['POST'])
def ask_maverick():
    data = request.get_json()
    message = data.get('message', '').strip().lower()
    for question, answer in knowledge_base.items():
        if message in question.lower():
            return jsonify({ "answer": answer })
    return jsonify({ "answer": "Sorry, I couldn't find an answer to that. Try rephrasing your question." })

@app.route('/')
def home():
    return '✅ Goose Prime is live. Visit /static/index.html'

if __name__ == '__main__':
    app.run(debug=True)
