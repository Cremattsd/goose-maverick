from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import os
from realnex_api import RealNexAPI

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'a-default-secret-key')

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    api_key = request.form.get('api_key')
    # Validate the API key by making a test request to the RealNex API
    realnex_api = RealNexAPI(api_key)
    try:
        test_response = realnex_api.fetch_data("test-endpoint")  # Replace with a valid endpoint
        if test_response.get("success"):
            # Store the API key in the session
            session['api_key'] = api_key
            return redirect(url_for('dashboard'))
    except Exception as e:
        return f"Invalid API Key: {str(e)}", 401

@app.route('/dashboard')
def dashboard():
    if 'api_key' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save the file temporarily
    file_path = f"/tmp/{file.filename}"
    file.save(file_path)

    # Upload the file to RealNex API
    api_key = session.get('api_key')
    if not api_key:
        return jsonify({"error": "Unauthorized"}), 401

    realnex_api = RealNexAPI(api_key)
    try:
        response = realnex_api.upload_file(file_path)
        return jsonify(response)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
