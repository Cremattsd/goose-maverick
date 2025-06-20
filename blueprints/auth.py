import jwt
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app

# Shared resources
from db import logger
from db_service import get_db  # provides `cursor, conn`

# Decorator from utility module
from auth_utils import token_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required—don’t leave me vacant! 🏢"}), 400

    cursor, conn = get_db()

    try:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()

        if not user:
            user_id = str(uuid.uuid4())
            created_at = datetime.now().isoformat()
            cursor.execute(
                "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                (user_id, email, created_at)
            )
            conn.commit()
            logger.info(f"New user created: {user_id} with email {email}—welcome to the CRE game! 🏙️")
        else:
            user_id = user[0]

        # Generate JWT token
        token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')

        logger.info(f"User logged in: {user_id}—they’re ready to close some CRE deals! 🤝")
        return jsonify({"token": token, "user_id": user_id})

    except Exception as e:
        logger.error(f"Failed to login user with email {email}: {e}")
        return jsonify({"error": f"Failed to login: {str(e)}"}), 500
