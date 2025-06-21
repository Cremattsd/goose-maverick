from flask import Blueprint, render_template, request, jsonify
from auth_utils import token_required
import openai
import os

main_routes = Blueprint('main_routes', __name__)

# Frontend Views
@main_routes.route("/")
def index():
    return render_template("index.html")

@main_routes.route("/chat-hub")
def chat_hub():
    return render_template("index.html")

@main_routes.route("/dashboard")
def dashboard():
    return render_template("main_dashboard.html")

@main_routes.route("/deal-trends")
def deal_trends():
    return render_template("deal_trends.html")

@main_routes.route("/ocr")
def ocr():
    return render_template("ocr.html")

@main_routes.route("/settings")
def settings():
    return render_template("settings.html")

@main_routes.route("/field-map")
def field_map():
    return render_template("field-map.html")

@main_routes.route("/activity")
def activity():
    return render_template("activity.html")

@main_routes.route("/login")
def login():
    return render_template("login.html")

# Chat Endpoint
@main_routes.route("/ask", methods=["POST"])
@token_required
def ask():
    query = request.json.get("query", "")
    if not query:
        return jsonify({"error": "Query is missing"}), 400

    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")
        response = openai.ChatCompletion.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4"),
            messages=[{"role": "user", "content": query}]
        )
        reply = response["choices"][0]["message"]["content"]
        return jsonify({"response": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
