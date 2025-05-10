# goose_backend_upgrade.py

import os
import json
import pytesseract
import requests
import exifread
import io
from PIL import Image
from geopy.geocoders import Nominatim
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

geolocator = Nominatim(user_agent="realnex_goose")
REALNEX_API_BASE = "https://sync.realnex.com/api/v1"

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

def create_contact_in_realnex(token, data):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    response = requests.post(f"{REALNEX_API_BASE}/Crm/contact", headers=headers, json=data)
    return response.status_code, response.json() if response.content else {}

@app.route('/upload-business-card', methods=['POST'])
def upload_business_card():
    token = request.form.get('token')
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
        "prospect": True
    }

    status, response = create_contact_in_realnex(token, contact_payload)

    return jsonify({
        "ocrText": ocr_text,
        "location": exif_data,
        "contactCreated": response,
        "status": status
    })

# === Load Knowledge Base for Maverick ===
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

if __name__ == '__main__':
    app.run(debug=True)
