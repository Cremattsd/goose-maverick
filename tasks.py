from flask import Blueprint, request, jsonify
from db import logger, cursor, conn
from blueprints.auth import token_required

tasks_bp = Blueprint('tasks', __name__)
socketio = None  # will be injected by app.py

def init_socketio(sio):
    global socketio
    socketio = sio

    @socketio.on("task_update", namespace="/tasks")
    def handle_task_update(data):
        logger.info(f"[TASK SOCKET] update received: {data}")
        socketio.emit("task_updated", data, namespace="/tasks")

@tasks_bp.route('', methods=['POST'])
@token_required
def create_task(user_id):
    data = request.get_json()
    logger.info(f"Creating task for user {user_id} with data: {data}")
    return jsonify({"status": "Task created (mock)"}), 200
