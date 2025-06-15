from flask import Blueprint, request, jsonify

main_routes = Blueprint('main_routes', __name__)
@token_required

@main_routes.route('/')
def index():
    return "Goose Maverick API is live"