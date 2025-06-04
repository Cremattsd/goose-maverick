from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
import jwt
import random
from functools import wraps

# Import shared resources
from db import logger, cursor, conn

auth_bp = Blueprint('auth', __name__)

def token_required(f):
    """Decorator to ensure a valid JWT token is present in the request."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            logger.warning("No token provided in request.")
            return jsonify({"error": "Token is missing—don’t leave me hanging like an unsigned lease! 📜"}), 401
        try:
            # Use current_app to access the Flask app's config
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            user_id = data.get('user_id', 'default')
            cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
            if not cursor.fetchone():
                logger.warning(f"User {user_id} not found.")
                return jsonify({"error": "User not found—are you a ghost tenant? 👻"}), 404
            return f(user_id, *args, **kwargs)
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired.")
            return jsonify({"error": "Token has expired—time to renew that lease! 🕒"}), 401
        except jwt.InvalidTokenError:
            logger.warning("Invalid token provided.")
            return jsonify({"error": "Invalid token—don’t try to sneak in without a key! 🔑"}), 401
    return decorated_function

@auth_bp.route('/set-token', methods=['POST'])
@token_required
def set_token(user_id):
    data = request.get_json()
    service = data.get('service')
    token = data.get('token')
    if not service or not token:
        return jsonify({"error": "Service and token are required—don’t make me chase you like a late rent payment! 💸"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO user_tokens (user_id, service, token) VALUES (?, ?, ?)",
                       (user_id, service, token))
        conn.commit()
        logger.info(f"Token set for service {service} for user {user_id}—locked in like a CRE contract! 🔒")
        return jsonify({"status": f"Token for {service} set successfully—ready to roll! 🚀"})
    except Exception as e:
        logger.error(f"Failed to set token for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set token: {str(e)}"}), 500

@auth_bp.route('/generate-2fa', methods=['POST'])
@token_required
def generate_2fa(user_id):
    try:
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        expiry = datetime.now() + timedelta(minutes=10)
        cursor.execute("INSERT OR REPLACE INTO two_fa_codes (user_id, code, expiry) VALUES (?, ?, ?)",
                       (user_id, code, expiry.isoformat()))
        conn.commit()
        logger.info(f"2FA code generated for user {user_id}: code={code}, expires={expiry}—they’re locked in tighter than a CRE vault! 🔒")
        return jsonify({"status": "2FA code generated", "code": code, "expiry": expiry.isoformat()})
    except Exception as e:
        logger.error(f"Failed to generate 2FA code for user {user_id}: {e}")
        return jsonify({"error": f"Failed to generate 2FA code: {str(e)}"}), 500

@auth_bp.route('/verify-2fa', methods=['POST'])
@token_required
def verify_2fa(user_id):
    data = request.get_json()
    code = data.get('code')
    if not code:
        return jsonify({"error": "Code is required—don’t leave me hanging like a bad lease deal! 🏢"}), 400

    try:
        cursor.execute("SELECT code, expiry FROM two_fa_codes WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if not result:
            return jsonify({"error": "No 2FA code found—did you forget to generate one? 🔑"}), 404

        stored_code, expiry = result
        expiry_time = datetime.fromisoformat(expiry)
        if datetime.now() > expiry_time:
            return jsonify({"error": "2FA code expired—faster than a hot property listing! ⏰"}), 400

        if code != stored_code:
            return jsonify({"error": "Invalid code—try again, champ! 🔐"}), 400

        # Code is valid, clean up
        cursor.execute("DELETE FROM two_fa_codes WHERE user_id = ?", (user_id,))
        conn.commit()
        logger.info(f"2FA code verified for user {user_id}—they’re in like a VIP tenant! 🏙️")
        return jsonify({"status": "2FA verified—welcome to the penthouse! 🏙️"})
    except Exception as e:
        logger.error(f"Failed to verify 2FA for user {user_id}: {e}")
        return jsonify({"error": f"Failed to verify 2FA: {str(e)}"}), 500
