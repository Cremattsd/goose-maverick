from flask import Flask, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
from config import *

# Shared resources
from db import logger, conn, cursor

# Blueprints
from blueprints.auth import auth_bp
from blueprints.chat import chat_bp, init_socketio as init_chat_socketio
from blueprints.contacts import contacts_bp
from blueprints.deals import deals_bp, init_socketio as init_deals_socketio
from blueprints.user import user_bp
from blueprints.tasks import tasks_bp, init_socketio as init_tasks_socketio
from blueprints.templates import templates_bp
from blueprints.reports import reports_bp
from blueprints.webhooks import webhooks_bp

# Initialize app
app = Flask(__name__, template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*")

# Register Blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(chat_bp, url_prefix='/chat')
app.register_blueprint(contacts_bp, url_prefix='/contacts')
app.register_blueprint(deals_bp, url_prefix='/deals')
app.register_blueprint(user_bp, url_prefix='/user')
app.register_blueprint(tasks_bp, url_prefix='/tasks')
app.register_blueprint(templates_bp, url_prefix='/templates')
app.register_blueprint(reports_bp, url_prefix='/reports')
app.register_blueprint(webhooks_bp, url_prefix='/webhooks')

# Initialize socket event handlers
init_chat_socketio(socketio)
init_deals_socketio(socketio)
init_tasks_socketio(socketio)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "Healthy—ready to close some CRE deals! 🏢"}), 200

if __name__ == "__main__":
    import os
    import eventlet
    eventlet.monkey_patch()

    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
