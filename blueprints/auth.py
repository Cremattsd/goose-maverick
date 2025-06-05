import jwt
import functools
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app

# Import shared resources
from db import logger, cursor, conn

auth_bp = Blueprint('auth', __name__)

def token_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"error": "Token is missing—don’t ghost me like an empty office space! 👻"}), 401

        try:
            if token.startswith('Bearer '):
                token = token.split(' ')[1]
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user_id = data['user_id']
            logger.info(f"Token validated for user {user_id}—they’re ready to roll in the CRE world! 🏢")
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired—time to renew that lease! ⏰"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token—looks like a bad deal! 🚫"}), 401

        return f(user_id, *args, **kwargs)
    return decorated

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required—don’t leave me vacant! 🏢"}), 400

    try:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        if not user:
            user_id = str(uuid.uuid4())
            created_at = datetime.now().isoformat()
            cursor.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                           (user_id, email, created_at))
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
