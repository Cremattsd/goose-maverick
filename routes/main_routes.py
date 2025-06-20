from flask import Blueprint, render_template, request, jsonify
from auth_utils import token_required  # ✅ Keep this for your API routes

main_routes = Blueprint('main_routes', __name__)

# Public route to serve the app UI
@main_routes.route("/")
def index():
    return render_template("index.html")

# Example protected route (unchanged)
@main_routes.route("/api/some-protected-endpoint")
@token_required
def protected_stuff():
    return jsonify({"status": "You’re authorized!"})
