import os
import logging
import uuid
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from realnex_api import RealNexAPI
import openai

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "your_secret_key"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# RealNex API Key (User-Generated ID)
REALNEX_API_KEY = os.getenv("REALNEX_API_KEY")
realnex = RealNexAPI(REALNEX_API_KEY)

# OpenAI API Key for AI-based field matching
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("home"))
    return render_template("dashboard.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files["file"]
    
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)

    logger.info(f"File {filename} uploaded successfully.")

    # AI-powered field extraction
    extracted_data = parse_document(file_path)
    return jsonify({"success": True, "data": extracted_data})


def parse_document(file_path):
    """
    Simulated document parsing function using OpenAI.
    """
    with open(file_path, "rb") as file:
        extracted_text = file.read().decode(errors="ignore")  # Simulated OCR

    logger.info(f"Extracted Text: {extracted_text[:200]}...")  # Log first 200 chars

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Extract key real estate data fields."},
            {"role": "user", "content": extracted_text}
        ]
    )
    
    parsed_data = response["choices"][0]["message"]["content"]
    return parsed_data


@app.route("/authenticate", methods=["POST"])
def authenticate():
    """
    Authenticate user via RealNex API and assign a unique session ID.
    """
    user_data = realnex.authenticate()
    if "error" in user_data:
        return jsonify({"error": user_data["error"]}), 401

    session["user_id"] = str(uuid.uuid4())  # Assign a unique session ID
    return jsonify({"success": True, "user_id": session["user_id"]})


if __name__ == "__main__":
    app.run(debug=True)