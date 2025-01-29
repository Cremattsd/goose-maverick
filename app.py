import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade

# Flask app initialization
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a-default-secret-key')

# RealNex API base URL (Update this if needed)
REALNEX_API_URL = "https://sync.realnex.com/api"

# Configure logging
logging.basicConfig(
    level=logging.INFO,  
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------------------- ROUTES ----------------------

# Home/Login Page
@app.route("/")
def home():
    logger.info("Home page accessed")
    return render_template("login.html")

# Login Route
@app.route("/login", methods=["POST"])
def login():
    try:
        # Ensure required fields are present
        if "email" not in request.form or "password" not in request.form:
            logger.error("Missing Email or Password in the request form")
            return "Email and Password are required", 400

        email = request.form.get("email")
        password = request.form.get("password")

        logger.info(f"Login attempt with Email: {email}")

        # Initialize SDK and authenticate
        client = RealNexSyncApiDataFacade(base_url=REALNEX_API_URL)
        auth_response = client.client.get_user(email=email, password=password)  # Modify as needed

        if not auth_response or "token" not in auth_response:
            logger.error("Invalid credentials or no user data returned")
            return "Invalid Email or Password", 401

        # Store session data
        session["user_token"] = auth_response["token"]
        session["client_name"] = auth_response.get("clientName", "User")
        session["full_name"] = auth_response.get("fullName", "User")

        logger.info(f"Login successful - Welcome {session['full_name']}")
        return redirect(url_for("dashboard"))

    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        return f"Login Error: {str(e)}", 401

# Dashboard Route
@app.route("/dashboard")
def dashboard():
    if "user_token" not in session:
        logger.warning("Unauthorized access to dashboard")
        return redirect(url_for("home"))
    
    logger.info("Dashboard accessed")
    client_name = session.get("full_name", "User")  
    return render_template("dashboard.html", client_name=client_name)

# File Upload Route
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        logger.error("No file uploaded")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        logger.error("No file selected")
        return jsonify({"error": "No file selected"}), 400

    # Save the file temporarily
    file_path = f"/tmp/{file.filename}"
    file.save(file_path)
    logger.info(f"File saved temporarily: {file_path}")

    # Upload file to RealNex API using SDK
    if "user_token" not in session:
        logger.error("Unauthorized access")
        return jsonify({"error": "Unauthorized"}), 401

    client = RealNexSyncApiDataFacade(api_key=session["user_token"], base_url=REALNEX_API_URL)

    try:
        upload_response = client.crm.upload_file(file_path)  # Replace with actual SDK method
        logger.info(f"File uploaded successfully: {file.filename}")
        return jsonify(upload_response)
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Logout Route
@app.route("/logout")
def logout():
    session.clear()
    logger.info("User logged out")
    return redirect(url_for("home"))

# ---------------------- RUN FLASK APP ----------------------
if __name__ == "__main__":
    app.run(debug=True)
