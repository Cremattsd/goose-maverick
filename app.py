import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from real_nex_sync_api_data_facade.sdk import RealNexAPI  # Importing from your SDK

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
    email = request.form.get('email')
    password = request.form.get('password')
    logger.info(f"Login attempt for user: {email}")

    # Use the RealNex SDK to authenticate
    client = RealNexAPI()
    auth_response = client.login(email, password)

    if "token" in auth_response:
        session['api_token'] = auth_response["token"]
        session['user_email'] = email  # Store user info in session
        logger.info(f"Login successful for {email}")
        return redirect(url_for('dashboard'))
    else:
        logger.error("Login failed")
        return "Login failed", 401

@app.route('/dashboard')
def dashboard():
    if 'api_token' not in session:
        logger.warning("Unauthorized access to dashboard")
        return redirect(url_for('home'))

    logger.info(f"Dashboard accessed by {session.get('user_email', 'Unknown User')}")
    return render_template('dashboard.html', client_name=session.get('user_email', 'User'))

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

    # Ensure user is authenticated
    api_token = session.get('api_token')
    if not api_token:
        logger.error("Unauthorized access")
        return jsonify({"error": "Unauthorized"}), 401

    # Use the RealNex SDK to upload the file
    client = RealNexAPI()
    client.token = api_token  # Use stored session token

    try:
        upload_response = client.upload_file(file_path)  # Use SDK's method
        logger.info(f"File uploaded successfully: {file.filename}")
        return jsonify(upload_response)
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
