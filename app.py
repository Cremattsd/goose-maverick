import logging
import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a-default-secret-key')

# RealNex API Base URL (Make sure it's correct)
REALNEX_API_URL = "https://sync.realnex.com/api"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Home Route (Login Page)
@app.route("/")
def home():
    logger.info("Home page accessed")
    return render_template("login.html")

# Login Route
@app.route("/login", methods=["POST"])
def login():
    api_key = request.form.get("api_key")
    logger.info(f"Login attempt with API Key: {api_key}")

    # Initialize SDK with API key
    client = RealNexSyncApiDataFacade(api_key=api_key, base_url=REALNEX_API_URL)

    # Test API Key by fetching client details
    headers = {"X-API-KEY": api_key}
    response = requests.get(f"{REALNEX_API_URL}/Client", headers=headers)

    if response.status_code == 200:
        user_data = response.json()
        session["api_key"] = api_key
        session["client_name"] = user_data.get("clientName", "User")  # Store Client Name
        logger.info(f"Login successful - Welcome {session['client_name']}")
        return redirect(url_for("dashboard"))
    else:
        logger.error(f"Invalid API Key: {response.text}")
        return f"Invalid API Key: {response.text}", 401

# Dashboard Route
@app.route("/dashboard")
def dashboard():
    if "api_key" not in session:
        logger.warning("Unauthorized access to dashboard")
        return redirect(url_for("home"))

    logger.info("Dashboard accessed")
    client_name = session.get("client_name", "User")
    return render_template("dashboard.html", client_name=client_name)

# Upload File Route
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        logger.error("No file uploaded")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        logger.error("No file selected")
        return jsonify({"error": "No file selected"}), 400

    file_path = f"/tmp/{file.filename}"
    file.save(file_path)
    logger.info(f"File saved temporarily: {file_path}")

    # Upload to RealNex API
    api_key = session.get("api_key")
    if not api_key:
        logger.error("Unauthorized access")
        return jsonify({"error": "Unauthorized"}), 401

    headers = {"X-API-KEY": api_key}
    files = {"file": open(file_path, "rb")}

    try:
        upload_response = requests.post(f"{REALNEX_API_URL}/Upload", headers=headers, files=files)
        logger.info(f"File uploaded successfully: {file.filename}")
        return jsonify(upload_response.json())
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Logout Route
@app.route("/logout")
def logout():
    session.clear()
    logger.info("User logged out")
    return redirect(url_for("home"))

# Run the Flask app
if __name__ == "__main__":
    app.run(debug=True)
