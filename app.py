from flask import Blueprint, request, jsonify
from blueprints.auth import token_required
from db import logger, cursor, conn

# Blueprint definition
tasks_bp = Blueprint('tasks', __name__)
socketio = None  # Will be injected later from app.py

def init_socketio(sio):
    global socketio
    socketio = sio

    @socketio.on('task_update', namespace='/tasks')
    def handle_task_update(data):
        print("Received task update:", data)

@tasks_bp.route('', methods=['GET'])
@token_required
def get_tasks(user_id):
    return jsonify({"tasks": []})


# app.py
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from db import logger, cursor, conn
from blueprints.auth import auth_bp
from blueprints.chat import chat_bp
from blueprints.contacts import contacts_bp
from blueprints.deals import deals_bp
from blueprints.tasks import tasks_bp, init_socketio
from blueprints.templates import templates_bp
from blueprints.reports import reports_bp
from blueprints.webhooks import webhooks_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(chat_bp, url_prefix='/chat')
app.register_blueprint(contacts_bp, url_prefix='/contacts')
app.register_blueprint(deals_bp, url_prefix='/deals')
app.register_blueprint(tasks_bp, url_prefix='/tasks')
app.register_blueprint(templates_bp, url_prefix='/templates')
app.register_blueprint(reports_bp, url_prefix='/reports')
app.register_blueprint(webhooks_bp, url_prefix='/webhooks')

# Inject socket into tasks
init_socketio(socketio)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000)
