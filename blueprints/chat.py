from flask import Blueprint, request, jsonify, redirect, url_for, render_template, current_app
from datetime import datetime
import httpx
import jwt
from flask_socketio import emit, join_room
from db import logger, cursor, conn
import commands

def create_chat_blueprint(socketio):
    chat_bp = Blueprint('chat', __name__)

    @socketio.on('connect', namespace='/chat')
    def handle_connect():
        logger.info("Client connected to /chat namespace")

    @socketio.on('disconnect', namespace='/chat')
    def handle_disconnect():
        logger.info("Client disconnected from /chat namespace")

    @socketio.on('join', namespace='/chat')
    def handle_join(data):
        user_id = data.get('user_id')
        if user_id:
            join_room(user_id)
            logger.info(f"User {user_id} joined room")

    @chat_bp.route('/', methods=['GET'])
    def index():
        return redirect(url_for('chat.chat_hub'))

    @chat_bp.route('/hub', methods=['GET'])
    def chat_hub():
        return render_template('index.html')

    @chat_bp.route('/chat', methods=['POST'])
    def chat():
        data = request.get_json()
        message = data.get('message')
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        user_id = None

        if not message:
            return jsonify({"error": "Message is required"}), 400

        # Decode JWT if present
        if token:
            try:
                decoded = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
                user_id = decoded.get("user_id")
            except jwt.InvalidTokenError:
                logger.warning("Invalid token used for chat")

        timestamp = datetime.now().isoformat()

        try:
            # Save user message
            cursor.execute(
                "INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                (user_id or "anonymous", "user", message, timestamp)
            )
            conn.commit()

            # Generate bot response
            bot_response = commands.process_message(message, user_id, cursor, conn, socketio) or f"Echo: {message}"

            # Save bot response
            cursor.execute(
                "INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                (user_id or "anonymous", "bot", bot_response, datetime.now().isoformat())
            )
            conn.commit()

            # Emit to user room if available
            socketio.emit('message', {
                "user_id": user_id,
                "sender": "bot",
                "message": bot_response,
                "timestamp": timestamp
            }, namespace='/chat', room=user_id or None)

            # Trigger webhook if applicable
            if user_id:
                cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
                webhook = cursor.fetchone()
                if webhook:
                    try:
                        httpx.post(webhook[0], json={
                            "user_id": user_id,
                            "message": message,
                            "response": bot_response,
                            "timestamp": timestamp
                        })
                    except Exception as e:
                        logger.error(f"Webhook failed: {e}")

            logger.info(f"Bot response: {bot_response}")
            return jsonify({"bot": bot_response})

        except Exception as e:
            logger.error(f"Chat processing error: {e}")
            return jsonify({"error": f"Server error: {str(e)}"}), 500

    @chat_bp.route('/history', methods=['GET'])
    @token_required
    def get_chat_history(user_id):
        try:
            cursor.execute(
                "SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,)
            )
            messages = [
                {"sender": row[0], "message": row[1], "timestamp": row[2]}
                for row in cursor.fetchall()
            ]
            return jsonify({"messages": messages})
        except Exception as e:
            logger.error(f"History error: {e}")
            return jsonify({"error": f"Could not fetch history: {str(e)}"}), 500

    @chat_bp.route('/ask', methods=['POST'])
    def ask():
        return chat()

    return chat_bp
