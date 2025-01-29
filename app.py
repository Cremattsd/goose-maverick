import logging
from flask import Flask, request, jsonify, render_template
import requests

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

REALNEX_API_URL = "https://sync.realnex.com/api/client"

@app.route("/")
def home():
    """Render the homepage."""
    logging.info("Home page accessed")
    return render_template("index.html")

@app.route("/login", methods=["POST"])
def login():
    """Authenticate user using their API token."""
    token = request.form.get("api_key")

    if not token:
        logging.error("No API token provided.")
        return jsonify({"error": "API Token is required"}), 400

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get(REALNEX_API_URL, headers=headers)
        logging.info(f"Login attempt with API Token: {token}")

        if response.status_code == 200:
            data = response.json()
            client_name = data.get("clientName", "Unknown User")
            logging.info(f"Login successful: Welcome, {client_name}!")
            return jsonify({"message": f"Welcome, {client_name}!"}), 200
        else:
            logging.error(f"Invalid API Token: {response.text}")
            return jsonify({"error": "Invalid API Token", "details": response.text}), response.status_code

    except requests.exceptions.RequestException as e:
        logging.error(f"Request Error: {e}")
        return jsonify({"error": "Request to RealNex failed", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
