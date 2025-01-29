from flask import Flask, render_template, request, redirect, url_for, session
import requests
import logging

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Change this to a strong, random secret key

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REALNEX_API_URL = "https://sync.realnex.com/api/Client"  # Update if needed

@app.route("/")
def home():
    """Render the homepage where users can enter their API Key."""
    return render_template("index.html")

@app.route("/login", methods=["POST"])
def login():
    """Handle login with API Key authentication."""
    api_key = request.form.get("api_key")  # Get API key from form input
    logger.info(f"Login attempt with API Key: {api_key}")

    if not api_key:
        logger.error("No API key provided.")
        return "API Key is required", 400

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(REALNEX_API_URL, headers=headers)
        response.raise_for_status()

        client_data = response.json()
        client_name = client_data.get("clientName", "User")  # Extract client name if available

        # Store API key & client name in session
        session["api_key"] = api_key
        session["client_name"] = client_name

        logger.info(f"Login successful! Welcome, {client_name}")
        return redirect(url_for("dashboard"))

    except requests.exceptions.RequestException as e:
        logger.error(f"Invalid API Key: {e}")
        return "Invalid API Key", 401

@app.route("/dashboard")
def dashboard():
    """Render the user dashboard if logged in."""
    if "api_key" not in session:
        return redirect(url_for("home"))  # Redirect to home if not logged in

    client_name = session.get("client_name", "User")
    return render_template("dashboard.html", client_name=client_name)

@app.route("/logout")
def logout():
    """Logout user by clearing the session."""
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
