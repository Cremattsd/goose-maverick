import os
from flask import Flask
from flask_socketio import SocketIO
from routes.main_routes import main_routes
from blueprints.chat import create_chat_blueprint
from blueprints.auth import auth_bp
from blueprints.contacts import contacts_bp
from blueprints.deals import deals_bp
from blueprints.tasks import tasks_bp
from blueprints.user import user_bp
from blueprints.webhooks import webhooks_bp

# Initialize Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "dev_secret_key")

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Register Blueprints
app.register_blueprint(main_routes)
app.register_blueprint(create_chat_blueprint(socketio), url_prefix="/chat")
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(contacts_bp, url_prefix="/contacts")
app.register_blueprint(deals_bp, url_prefix="/deals")
app.register_blueprint(tasks_bp, url_prefix="/tasks")
app.register_blueprint(user_bp, url_prefix="/user")
app.register_blueprint(webhooks_bp, url_prefix="/webhooks")

# Entry point
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
