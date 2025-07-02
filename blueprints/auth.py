from auth_utils import token_required  # still used for route protection elsewhere
from flask import Blueprint, jsonify

auth_bp = Blueprint('auth', __name__)

# Block unused login route – all auth happens via settings input
@auth_bp.route('/login', methods=['GET', 'POST'])
def login_disabled():
    return jsonify({
        "message": "Login is disabled. Please request a JWT token via support@realnex.com and paste it into Settings."
    }), 403
