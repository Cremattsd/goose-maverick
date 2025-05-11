import os
import json
import logging
import requests
import pandas as pd
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
import openai
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"

# ✅ Correct OpenAI API key setup
openai.api_key = os.getenv("OPENAI_API_KEY")

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
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        system_prompt = (
            "You are Maverick, a knowledgeable assistant specializing in commercial real estate, RealNex, Pix-Virtual, Pixl Imaging, and ViewLabs. "
            "Answer clearly and helpfully, focusing only on these topics."
        )

        response = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )

        answer = response.choices[0].message["content"]
        return jsonify({"answer": answer})
    except Exception as e:
        logging.error(f"OpenAI error: {str(e)}")
        return jsonify({"error": f"OpenAI error: {str(e)}"}), 500

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
        logging.error(f"Validation error: {str(e)}")
        return jsonify({"error": f"Error validating token: {str(e)}"}), 500

@app.route('/terms', methods=['GET'])
def get_terms():
    return jsonify({
        "text": (
            "Protection of data is paramount to RealNex. By using the RealNex Services, you agree to abide by the Terms of Use. "
            "You represent that you are the owner of all data uploaded and have legal authority to upload it."
        )
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
