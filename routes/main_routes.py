from flask import Blueprint, render_template, request, jsonify
from auth_utils import token_required

main_routes = Blueprint('main_routes', __name__)

# Public UI routes
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

@main_routes.route("/settings")
def settings():
    return render_template("settings.html")

@main_routes.route("/ocr")
def ocr():
    return render_template("ocr.html")

@main_routes.route("/activity")
def activity():
    return render_template("activity.html")

@main_routes.route("/field-map")
def field_map():
    return render_template("field-map.html")

@main_routes.route("/login")
def login():
    return render_template("login.html")

@main_routes.route("/duplicates")
def duplicates():
    return render_template("duplicates_dashboard.html")  # If you add this one later

# Example protected API route
@main_routes.route("/api/some-protected-endpoint")
@token_required
def protected_stuff():
    return jsonify({"status": "You’re authorized!"})
