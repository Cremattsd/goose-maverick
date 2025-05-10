import os
import json
import logging
import requests
import pandas as pd
import tempfile
import openai
from flask import Flask, request, jsonify, send_from_directory, render_template
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
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

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")

CONSTANT_CONTACT_API_KEY = os.getenv("CONSTANT_CONTACT_API_KEY")
CONSTANT_CONTACT_ACCESS_TOKEN = os.getenv("CONSTANT_CONTACT_ACCESS_TOKEN")
CONSTANT_CONTACT_LIST_ID = os.getenv("CONSTANT_CONTACT_LIST_ID")

DEFAULT_CAMPAIGN_MODE = os.getenv("DEFAULT_CAMPAIGN_MODE", "realnex")
UNLOCK_EMAIL_PROVIDER_SELECTION = os.getenv("UNLOCK_EMAIL_PROVIDER_SELECTION", "false").lower() == "true"

TERMS_MESSAGE = (
    "Protection of data is paramount to RealNex. By uploading data, you agree to the RealNex Terms of Use "
    "(https://realnex.com/Terms). You represent you own the data or have the right to use it, and agree to "
    "indemnify RealNex for any claims from misuse.")

@app.route("/ask", methods=["POST"])
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
            "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        }

        response = openai.ChatCompletion.create(**chat_request)
        answer = response.choices[0].message["content"]
        logging.info(f"User asked: {user_message}, Answered: {answer}")
        return jsonify({"answer": answer})
    except Exception as e:
        logging.error(f"OpenAI error: {str(e)}")
        return jsonify({"error": f"OpenAI error: {str(e)}"}), 500
