from flask import Flask, render_template, request, redirect, url_for, session, flash
import requests
import logging

app = Flask(__name__)
app.secret_key = "your_secret_key"

REALNEX_API_URL = "https://sync.realnex.com/api"

logging.basicConfig(level=logging.INFO)

@app.route("/")
def home():
    if "user_name" in session:
        return render_template("dashboard.html", user_name=session["user_name"])
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        api_key = request.form.get("api_key")
        headers = {"Authorization": f"Bearer {api_key}"}

        response = requests.get(f"{REALNEX_API_URL}/Client", headers=headers)

        if response.status_code == 200:
            user_data = response.json()
            session["user_name"] = user_data.get("clientName", "Unknown User")  # Store user's name
            session["api_key"] = api_key  # Store API key for future use
            logging.info(f"User logged in: {session['user_name']}")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid API Key. Please try again.", "danger")
            logging.error(f"Login failed: {response.text}")

    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user_name" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user_name=session["user_name"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)
