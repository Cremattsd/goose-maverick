import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade

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

REALNEX_API_URL = "https://sync.realnex.com/api"  # Update if needed

# Routes
@app.route('/')
def home():
    logger.info("Home page accessed")
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    api_key = request.form.get('api_key')  # Get API key from the form
    logger.info(f"Login attempt with API key: {api_key}")

    if not api_key:
        logger.error("API Key is required")
        return "API Key is required", 400

    try:
        # Initialize SDK with the API key
        client = RealNexSyncApiDataFacade(api_key=api_key, base_url=REALNEX_API_URL)

        # Fetch client information
        client_info = client.client.get_user()
        
        # Extract the client's full name
        full_name = getattr(client_info, 'user_name', 'User')  # Default to 'User' if missing

        # Store user details in the session
        session['api_key'] = api_key
        session['full_name'] = full_name

        logger.info(f"Login successful - Welcome {full_name}")
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
    client_name = session.get('full_name', 'User')  # Show full name instead of email
    return render_template('dashboard.html', client_name=client_name)

# Run the app
if __name__ == '__main__':
    app.run(debug=True)
