import os
import json
import logging
import requests
import pandas as pd
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from openai import OpenAI, APIError
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

# === App Setup ===
app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

# === Environment ===
REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === Retryable RealNex Helpers ===
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def realnex_post(endpoint, token, data):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
    response.raise_for_status()
    return response.status_code, response.json() if response.content else {}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def realnex_get(endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
    response.raise_for_status()
    return response.status_code, response.json().get("value", [])

def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    return realnex_post("/Crm/history", token, payload)

# === Routes ===
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        system_prompt = (
            "You are Maverick, a knowledgeable assistant trained in commercial real estate, RealNex, Pix-Virtual, and ViewLabs. "
            "Only answer questions about these topics. Redirect others politely."
        )

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )

        answer = response.choices[0].message.content
        logging.info(f"User asked: {user_message} — Answer: {answer}")
        return jsonify({"answer": answer})
    except APIError as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error in /ask: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/validate-token', methods=['POST'])
def validate_token():
    try:
        token = request.json.get("token", "").strip()
        if not token:
            return jsonify({"error": "Token is required"}), 400

        status, _ = realnex_get("Contacts?$top=1", token)
        return jsonify({"valid": status == 200})
    except Exception as e:
        logging.error(f"Token validation error: {str(e)}")
        return jsonify({"error": f"Token validation failed: {str(e)}"}), 500

@app.route('/terms', methods=['GET'])
def get_terms():
    return jsonify({
        "text": (
            "By using the RealNex Services, you agree you are authorized to upload this data and indemnify RealNex from any third-party intellectual property claims. "
            "See https://realnex.com/Terms for full terms of use."
        )
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
