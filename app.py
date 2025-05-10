import os
import openai
import pytesseract
import exifread
import requests
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from PIL import Image
from geopy.geocoders import Nominatim
from datetime import datetime

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Set your OpenAI key from Render env
openai.api_key = os.getenv("OPENAI_API_KEY")
REALNEX_API_BASE = "https://sync.realnex.com/api/v1"
geolocator = Nominatim(user_agent="realnex_goose")

# === Routes ===

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/ask', methods=['POST'])
def ask():
    user_message = request.json.get("message", "").strip()
    if not user_message:
        return jsonify({"answer": "Please enter a message."})

    system_prompt = (
        "You are Maverick, an expert assistant focused on commercial real estate, RealNex, Pix-Virtual, and ViewLabs. "
        "Always greet on first message, stay on-topic, and politely deflect anything unrelated."
    )

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
    )

    return jsonify({"answer": response['choices'][0]['message']['content']})

@app.route('/upload-business-card', methods=['POST'])
def upload_business_card():
    token = request.form.get('token') or request.json.get('token')
    notes = request.form.get('notes', '') if request.form else ''
    file = request.files.get('file') if request.files else None

    if not file or not token:
        return jsonify({"error": "Missing file or token."}), 400

    path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(path)

    text = pytesseract.image_to_string(Image.open(path))
    lines = text.splitlines()
    name = next((l for l in lines if len(l.split()) >= 2), "")
    email = next((l for l in lines if "@" in l), "")
    phone = next((l for l in lines if any(c.isdigit() for c in l) and '-' in l), "")

    exif = extract_exif_location(path)
    contact = {"fullName": name.strip(), "email": email.strip(), "work": phone.strip(), "prospect": True}
    if notes:
        contact["notes"] = notes.strip()

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}/Crm/contact", headers=headers, json=contact)
    result = response.json() if response.content else {}

    return jsonify({
        "ocrText": text,
        "location": exif,
        "contactCreated": result,
        "status": response.status_code
    })

# === Helper for EXIF Location ===
def extract_exif_location(image_path):
    with open(image_path, 'rb') as f:
        tags = exifread.process_file(f)

    def _deg(v):
        d, m, s = v.values
        return d.num/d.den + m.num/m.den/60 + s.num/s.den/3600

    if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
        lat = _deg(tags['GPS GPSLatitude'])
        lon = _deg(tags['GPS GPSLongitude'])
        if tags['GPS GPSLatitudeRef'].values != 'N': lat = -lat
        if tags['GPS GPSLongitudeRef'].values != 'E': lon = -lon
        location = geolocator.reverse((lat, lon), exactly_one=True)
        return {"lat": lat, "lon": lon, "address": location.address if location else None}
    return None

if __name__ == '__main__':
    app.run(debug=True)
