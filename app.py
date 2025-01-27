import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from werkzeug.utils import secure_filename
from realnex_api import RealNexAPI

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a-default-secret-key')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    api_key = request.form.get('api_key')
    logger.info("Attempting login")
    realnex_api = RealNexAPI(api_key)
    auth_response = realnex_api.authenticate()
    
    if "error" not in auth_response:
        session['api_key'] = api_key
        session['client_name'] = auth_response.get("clientName", "User")
        logger.info("Login successful")
        return redirect(url_for('dashboard'))
    else:
        error_message = auth_response.get('error', 'Unknown error')
        logger.error(f"Login failed: {error_message}")
        return render_template('login.html', error=error_message), 401

@app.route('/dashboard')
def dashboard():
    if 'api_key' not in session:
        logger.warning("Unauthorized access to dashboard")
        return redirect(url_for('home'))
    
    logger.info("Dashboard accessed")
    client_name = session.get('client_name', 'User')
    return render_template('dashboard.html', client_name=client_name)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        logger.error("No file uploaded in request")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        logger.error("Empty file selected for upload")
        return jsonify({"error": "No file selected"}), 400

    # Secure and save the file temporarily
    filename = secure_filename(file.filename)
    file_path = os.path.join("/tmp", filename)
    file.save(file_path)
    logger.info(f"File saved temporarily at: {file_path}")

    # Upload file to RealNex API
    api_key = session.get('api_key')
    if not api_key:
        logger.error("Unauthorized upload attempt")
        return jsonify({"error": "Unauthorized"}), 401

    realnex_api = RealNexAPI(api_key)
    try:
        upload_response = realnex_api.upload_file(file_path)
    finally:
        # Cleanup temporary file
        os.remove(file_path)
        logger.info(f"Temporary file deleted: {file_path}")

    if "error" not in upload_response:
        logger.info(f"File uploaded successfully: {filename}")
        return jsonify(upload_response)
    else:
        error_message = upload_response.get('error', 'Unknown error')
        logger.error(f"Error uploading file: {error_message}")
        return jsonify({"error": error_message}), 500

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
