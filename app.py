import os
import json
import logging
import requests
import pandas as pd
import tempfile
import openai
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime, timedelta
from tenacity import retry, stop_after_attempt, wait_exponential
from goose_parser_tools import extract_text_from_image, extract_text_from_pdf, extract_exif_location, is_business_card, parse_ocr_text, suggest_field_mapping, map_fields

app = Flask(__name__, static_folder='static', static_url_path='')
UPLOAD_FOLDER = 'upload'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logging.basicConfig(level=logging.INFO, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')

REALNEX_API_BASE = os.getenv("REALNEX_API_BASE", "https://sync.realnex.com/api/v1")
ODATA_BASE = f"{REALNEX_API_BASE}/CrmOData"
openai.api_key = os.getenv("OPENAI_API_KEY")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_post(endpoint, token, data):
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(f"{REALNEX_API_BASE}{endpoint}", headers=headers, json=data)
        response.raise_for_status()
        return response.status_code, response.json() if response.content else {}
    except requests.RequestException as e:
        logging.error(f"RealNex POST failed: {str(e)}")
        return 500, {"error": f"API request failed: {str(e)}"}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def realnex_get(endpoint, token):
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{ODATA_BASE}/{endpoint}", headers=headers)
        response.raise_for_status()
        return response.status_code, response.json().get('value', [])
    except requests.RequestException as e:
        logging.error(f"RealNex GET failed: {str(e)}")
        return 500, {"error": f"API request failed: {str(e)}"}

def create_history(token, subject, notes, object_key=None, object_type="contact"):
    payload = {
        "subject": subject,
        "notes": notes,
        "event_type_key": "Weblead"
    }
    if object_key:
        payload[f"{object_type}_key"] = object_key
    status, result = realnex_post("/Crm/history", token, payload)
    if status not in [200, 201]:
        logging.error(f"Failed to create history: {result}")
    return status, result

@app.route('/')
def index():
    try:
        return app.send_static_file('index.html')
    except Exception as e:
        logging.error(f"Failed to serve index.html: {str(e)}")
        return jsonify({"error": "Failed to load frontend"}), 500

@app.route('/ask', methods=['POST'])
def ask():
    try:
        user_message = request.json.get("message", "").strip()
        if not user_message:
            return jsonify({"error": "Please enter a message."}), 400

        system_prompt = (
            "You are Maverick, a knowledgeable chat assistant specializing in commercial real estate, RealNex, Zendesk, webinars, Pix-Virtual (pix-virtual.com), Pixl Imaging, and ViewLabs. "
            "Provide helpful, on-topic answers about these subjects, including general information, best practices, or troubleshooting tips. "
            "Note that RealNex users authenticate with a bearer token, not an API key, though you do not need one to answer questions. "
            "Pix-Virtual offers virtual reality solutions for real estate, including QuickTour, RealFit, and PropertyMax for marketing properties. "
            "Pixl Imaging provides business card design and OCR solutions. "
            "If the user asks about something unrelated, politely redirect them to these topics."
        )

        if 'upload' in user_message.lower() and 'listing' in user_message.lower():
            return jsonify({
                "answer": "Sure thing! You can download the official RealNex listing upload template here: /download-listing-template. Fill it out and send it to support@realnex.com."
            })

        chat_request = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4-turbo"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        }

        response = openai.ChatCompletion.create(**chat_request)
        answer = response.choices[0].message["content"]
        logging.info(f"User asked: {user_message}, Answered: {answer}")
        return jsonify({"answer": answer})
    except openai.OpenAIError as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return jsonify({"error": f"OpenAI API error: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error in /ask: {str(e)}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

@app.route('/download-listing-template', methods=['GET'])
def download_listing_template():
    try:
        return send_from_directory('static', 'realnex_listing_template.xlsx', as_attachment=True)
    except Exception as e:
        logging.error(f"Failed to serve listing template: {str(e)}")
        return jsonify({"error": "Failed to download listing template"}), 500

@app.route('/get-listing-instructions', methods=['GET'])
def get_listing_instructions():
    return jsonify({
        "message": "To upload your listings to RealNex, please download the official template using /download-listing-template. Fill it out and send the completed version to support@realnex.com."
    })
