import os
from flask import Flask, redirect, url_for
from flask_socketio import SocketIO

# Blueprints
from routes.main_routes import main_routes
from blueprints.chat import create_chat_blueprint
from blueprints.auth import auth_bp
from blueprints.contacts import contacts_bp
from blueprints.deals import deals_bp
from blueprints.tasks import create_tasks_blueprint
from blueprints.user import user_bp
from blueprints.webhooks import webhooks_bp

# --- App Initialization ---
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "dev_secret_key")

# SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Register Blueprints ---
app.register_blueprint(main_routes)
app.register_blueprint(create_chat_blueprint(socketio), url_prefix="/chat")
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(contacts_bp, url_prefix="/contacts")
app.register_blueprint(deals_bp, url_prefix="/deals")
app.register_blueprint(create_tasks_blueprint(socketio), url_prefix="/tasks")
app.register_blueprint(user_bp, url_prefix="/user")
app.register_blueprint(webhooks_bp, url_prefix="/webhooks")

# --- Optional: Redirect home to chat ---
@app.route('/')
def home():
    return redirect(url_for('chat.chat_hub'))

# --- Optional: Health check endpoint ---
@app.route('/ping')
def ping():
    return {"status": "ok"}

# --- Entry Point ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
