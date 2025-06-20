from flask import Blueprint, request, jsonify
from db import logger, cursor, conn
from blueprints.auth import token_required
from datetime import datetime

def create_tasks_blueprint(socketio):
    tasks_bp = Blueprint('tasks', __name__)

    @tasks_bp.route('/ping', methods=['GET'])
    @token_required
    def ping(user_id):
        logger.info(f"[TASKS] Pinged by user {user_id}")
        socketio.emit('ping_response', {'message': 'pong'}, namespace='/chat', to=user_id)
        return jsonify({"message": "pong"}), 200

    @tasks_bp.route('/log', methods=['POST'])
    @token_required
    def log_action(user_id):
        data = request.get_json()
        action = data.get('action')
        details = data.get('details', '')
        if not action:
            return jsonify({"error": "Action is required"}), 400

        try:
            timestamp = datetime.now().isoformat()
            cursor.execute("INSERT INTO user_activity_log (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, action, details, timestamp))
            conn.commit()
            logger.info(f"[TASKS] Logged action '{action}' for user {user_id}")
            return jsonify({"status": "Logged"}), 201
        except Exception as e:
            logger.error(f"[TASKS] Failed to log action: {e}")
            return jsonify({"error": "Logging failed"}), 500

    return tasks_bp
