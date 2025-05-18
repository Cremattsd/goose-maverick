import json
import logging
import os
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from openai import OpenAI
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
from datetime import datetime
import pandas as pd

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Cache field definitions
FIELD_DEFINITIONS = {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def load_field_definitions(token):
    global FIELD_DEFINITIONS
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{REALNEX_API_BASE}/Crm/definitions", headers=headers)
    response.raise_for_status()
    tables = response.json()
    for table in tables:
        response = requests.get(f"{REALNEX_API_BASE}/Crm/definitions/{table}", headers=headers)
        response.raise_for_status()
        FIELD_DEFINITIONS[table] = response.json()
    return FIELD_DEFINITIONS

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    response.raise_for_status()
    return response.status_code, response.json() if response.content else {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_get(endpoint, token, is_odata=False):
    headers = {"Authorization": f"Bearer {token}"}
    base = ODATA_BASE if is_odata else REALNEX_API_BASE
    response = requests.get(f"{base}/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.status_code, response.json().get('value', response.json())

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_user_id(token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{REALNEX_API_BASE}/Client?api-version=1.0", headers=headers)
    response.raise_for_status()
    return response.json().get('key')

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def match_property_by_geolocation(lat, lon, token):
    headers = {"Authorization": f"Bearer {token}"}
    query = f"Properties?$filter=latitude eq {lat} and longitude eq {lon}&$top=1"
    response = requests.get(f"{ODATA_BASE}/{query}", headers=headers)
    response.raise_for_status()
    properties = response.json().get('value', [])
    return properties[0].get('crm_property_key') if properties else None

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/validate-token', methods=['POST'])
def validate_token():
    try:
        token = request.json.get('token', '').strip()
        if not token:
            return jsonify({"valid": False, "error": "No token provided"}), 400
        status, _ = realnex_get("Client?api-version=1.0", token)
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
        if user_message == "!deals":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            status, deals = realnex_get("SaleComps?$top=3", token, is_odata=True)
            return jsonify({"answer": f"Latest deals: {json.dumps(deals, indent=2)}" if status == 200 else "Turbulence fetching deals!"})
        if user_message == "!events":
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                return jsonify({"answer": "No token, Maverick! Lock in! 🔒"})
            user_id = get_user_id(token)
            status, events = realnex_get(f"Events?$filter=userId eq {user_id}&$top=5", token, is_odata=True)
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
def suggest_mapping():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        if not file.filename.lower().endswith('.xlsx'):
            return jsonify({"error": "Only Excel files supported for mapping!"}), 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        df = pd.read_excel(save_path)
        global FIELD_DEFINITIONS
        if not FIELD_DEFINITIONS:
            return jsonify({"error": "Field definitions not loaded. Validate token first!"}), 400
        suggested_mapping = suggest_field_mapping(df, FIELD_DEFINITIONS)
        return jsonify({"suggestedMapping": suggested_mapping})
    except Exception as e:
        logging.error(f"Suggest mapping error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/bulk-import', methods=['POST'])
def bulk_import():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded, Goose! 📄"}), 400
        file = request.files['file']
        token = request.form.get('token', '').strip()
        mapping = json.loads(request.form.get('mapping', '{}'))
        if not token or not mapping:
            return jsonify({"error": "Missing token or mapping! 🔒"}), 400

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        df = pd.read_excel(save_path)
        user_id = get_user_id(token)
        processed = 0
        results = []
        df.columns = df.columns.str.lower()
        for _, row in df.iterrows():
            for entity, fields in mapping.items():
                mapped = map_fields(row, fields)
                if mapped:
                    mapped["user"] = {"key": user_id}
                    if entity == "Properties" and "latitude" in mapped and "longitude" in mapped:
                        property_key = match_property_by_geolocation(mapped["latitude"], mapped["longitude"], token)
                        if property_key:
                            mapped["crm_property_key"] = property_key
                            results.append({"type": "PropertyMatch", "message": f"Geo-matched to Property Key: {property_key}"})
                            space = {
                                "crm_property_key": property_key,
                                "suite": mapped.get("suite", "Unknown"),
                                "user": {"key": user_id},
                                "sqft": mapped.get("sqft", 1000.0)
                            }
                            status, space_result = realnex_post("/Crm/Spaces", token, space)
                            results.append({"type": "Space", "status": status, "data": space_result})
                    endpoint = f"/Crm{entity}"
                    status, result = realnex_post(endpoint, token, mapped)
                    results.append({"type": entity, "status": status, "data": result})
                    processed += 1

        return jsonify({"processed": processed, "results": results})
    except Exception as e:
        logging.error(f"Bulk import error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

@app.route('/upload-business-card', methods=['POST'])
def upload_business_card():
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
            FIELD_DEFINITIONS = load_field_definitions(token)

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        user_id = get_user_id(token)
        results = []
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            text = extract_text_from_image(save_path)
            location = extract_exif_location(save_path)
            property_key = None
            if location:
                property_key = match_property_by_geolocation(location['latitude'], location['longitude'], token)
                if property_key:
                    results.append({"type": "PropertyMatch", "message": f"Geo-matched to Property Key: {property_key}"})
            
            if is_business_card(text):
                parsed = parse_ocr_text(text)
                parsed["user"] = {"key": user_id}
                parsed["notes"] = notes
                if location:
                    parsed["latitude"] = location["latitude"]
                    parsed["longitude"] = location["longitude"]
                status, result = realnex_post("/CrmContacts", token, parsed)
                results.append({"type": "Contact", "status": status, "data": result, "followUpEmail": parsed.get("email", "")})
            else:
                parsed = {"name": text[:50], "user": {"key": user_id}, "notes": notes}
                if location:
                    parsed["latitude"] = location["latitude"]
                    parsed["longitude"] = location["longitude"]
                if property_key:
                    parsed["crm_property_key"] = property_key
                status, result = realnex_post("/Crm/Properties", token, parsed)
                results.append({"type": "Property", "status": status, "data": result})
                if property_key:
                    space = {
                        "crm_property_key": property_key,
                        "suite": "Auto-Generated",
                        "user": {"key": user_id},
                        "sqft": 1000.0
                    }
                    status, space_result = realnex_post("/Crm/Spaces", token, space)
                    results.append({"type": "Space", "status": status, "data": space_result})
        elif filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(save_path)
            parsed = {"name": text[:50], "user": {"key": user_id}, "notes": notes}
            status, result = realnex_post("/Crm/Properties", token, parsed)
            results.append({"type": "Property", "status": status, "data": result})

        return jsonify({"message": f"Data synced to RealNex! Clear for takeoff! 🛫", "results": results, "followUpEmail": results[0]["data"].get("email", "") if results and results[0]["type"] == "Contact" else ""})
    except Exception as e:
        logging.error(f"Upload error: {str(e)}")
        return jsonify({"error": f"Turbulence: {str(e)}"}), 500

HELP_MESSAGE = """
🎯 *Goose-Maverick: Tech Stack & Usage Guide* 🎯
- *Backend*: Flask (Python) powers API routes (/ask, /upload-business-card, /bulk-import). Our jet engine!
- *Frontend*: Tailwind CSS for slick styling, Chart.js for gauges, vanilla JS for drag-and-drop in a floating chat widget. The cockpit!
- *Parsing*: Goose uses pandas for Excel, pytesseract/pdf2image/Pillow for OCR, EXIF for geolocation. Data radar locked!
- *APIs*: RealNex V1 OData (/CrmOData) fetches user IDs and events; non-OData (/CrmContacts) syncs data. OpenAI (GPT-4o) runs chat, ready for Grok 3!
- *Field Matching*: Pulls schemas from /api/v1/Crm/definitions to auto-match fields for Contacts, Properties, Spaces, SaleComps.
- *Geolocation*: Photos’ EXIF data matches Properties/Spaces via latitude/longitude in OData queries.
- *Usage*:
  1. Switch to Goose mode, enter your RealNex Bearer token (from RealNex dashboard).
  2. Drag-and-drop photos (.png, .jpg), PDFs, or Excel (.xlsx) into the chat widget.
  3. For photos/PDFs, add notes and sync as Contacts or Properties. Photos geo-match to Properties/Spaces.
  4. For Excel, review/edit suggested field mappings, then import.
  5. Chat with Maverick for help, CRM queries (‘Show my events’), or commands like `!maverick`!
- *Commands*: `!help` (this guide), `!maverick` (surprise), `!deals` (SaleComps), `!events` (your events).
- *Deploy*: Dockerized, deployable to Render (like mattys-drag-drop-app.onrender.com). Built to soar!
Ask ‘How do I sync SaleComps?’ or ‘How does geolocation work?’ for more! 😎
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
