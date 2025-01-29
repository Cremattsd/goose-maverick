import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade  # Corrected import

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a-default-secret-key')

# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Log format
    handlers=[
        logging.FileHandler('app.log'),  # Log to a file
        logging.StreamHandler()  # Log to the console
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
    logger.info(f"Login attempt with API key: {api_key}")

    # Initialize RealNex SDK client using the correct class
    client = RealNexSyncApiDataFacade(api_key=api_key)

    try:
        # Authenticate using the SDK
        auth_response = client.client.get_client()  
        session['api_key'] = api_key
        session['client_name'] = auth_response.get("clientName", "User")  
        session['full_name'] = auth_response.get("fullName", "User")  
        logger.info(f"Login successful - Welcome {session['full_name']}")
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error(f"Login failed: {str(e)}")
        return f"Invalid API Key: {str(e)}", 401

@app.route('/dashboard')
def dashboard():
    if 'api_key' not in session:
        logger.warning("Unauthorized access to dashboard")
        return redirect(url_for('home'))
    logger.info("Dashboard accessed")
    client_name = session.get('full_name', 'User')  
    return render_template('dashboard.html', client_name=client_name)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        logger.error("No file uploaded")
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        logger.error("No file selected")
        return jsonify({"error": "No file selected"}), 400

    # Save the file temporarily
    file_path = f"/tmp/{file.filename}"
    file.save(file_path)
    logger.info(f"File saved temporarily: {file_path}")

    # Upload the file to RealNex API using the SDK
    api_key = session.get('api_key')
    if not api_key:
        logger.error("Unauthorized access")
        return jsonify({"error": "Unauthorized"}), 401

    client = RealNexSyncApiDataFacade(api_key=api_key)

    try:
        upload_response = client.crm_attachment.upload_file(file_path)  # Replace with actual SDK method
        logger.info(f"File uploaded successfully: {file.filename}")
        return jsonify(upload_response)
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
