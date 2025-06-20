from flask import Blueprint, request, jsonify, redirect, url_for, render_template
from datetime import datetime
import httpx
import commands
from db import logger, cursor, conn
from flask_socketio import emit, join_room
from blueprints.auth import token_required

def create_chat_blueprint(socketio):
    chat_bp = Blueprint('chat', __name__)

    # SocketIO event handlers
    @socketio.on('connect', namespace='/chat')
    def handle_connect():
        logger.info("Client connected to /chat namespace—time to chat like a CRE pro! 💬")

    @socketio.on('disconnect', namespace='/chat')
    def handle_disconnect():
        logger.info("Client disconnected from /chat namespace—hope they signed the lease before leaving! 📝")

    @socketio.on('join', namespace='/chat')
    def handle_join(data):
        user_id = data.get('user_id')
        if user_id:
            join_room(user_id)
            logger.info(f"User {user_id} joined SocketIO room—ready to chat about CRE deals! 💬")

    # HTTP route handlers
    @chat_bp.route('/', methods=['GET'])
    @token_required
    def index(user_id):
        logger.info("Redirecting to chat hub—like a CRE agent pointing you to the best property! 🏢")
        return redirect(url_for('chat.chat_hub'))

    @chat_bp.route('/hub', methods=['GET'])
    @token_required
    def chat_hub(user_id):
        return render_template('index.html')

    @chat_bp.route('/chat', methods=['POST'])
    @token_required
    def chat(user_id):
        data = request.get_json()
        message = data.get('message')
        if not message:
            return jsonify({"error": "Message is required—don’t ghost me like an empty office space! 👻"}), 400

        try:
            timestamp = datetime.now().isoformat()
            cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, "user", message, timestamp))
            conn.commit()

            bot_response = commands.process_message(message, user_id, cursor, conn, socketio)
            if not bot_response:
                bot_response = f"Echo from the CRE world: {message}—let’s lease this conversation! 🏢"

            cursor.execute("INSERT INTO chat_messages (user_id, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                           (user_id, "bot", bot_response, datetime.now().isoformat()))
            conn.commit()

            socketio.emit('message', {
                "user_id": user_id,
                "sender": "bot",
                "message": bot_response,
                "timestamp": timestamp
            }, namespace='/chat')

            cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
            webhook = cursor.fetchone()
            if webhook:
                webhook_url = webhook[0]
                try:
                    with httpx.Client() as client:
                        client.post(webhook_url, json={
                            "user_id": user_id,
                            "message": message,
                            "response": bot_response,
                            "timestamp": timestamp
                        })
                except Exception as e:
                    logger.error(f"Failed to send webhook notification for user {user_id}: {e}")

            logger.info(f"Chat message processed for user {user_id}: {message}—they’re chatting like a CRE pro! 💬")
            return jsonify({"status": "Message processed", "response": bot_response})

        except Exception as e:
            logger.error(f"Failed to process chat message for user {user_id}: {e}")
            return jsonify({"error": f"Failed to process message: {str(e)}"}), 500

    @chat_bp.route('/history', methods=['GET'])
    @token_required
    def get_chat_history(user_id):
        try:
            cursor.execute("SELECT sender, message, timestamp FROM chat_messages WHERE user_id = ? ORDER BY timestamp ASC",
                           (user_id,))
            messages = [{"sender": row[0], "message": row[1], "timestamp": row[2]} for row in cursor.fetchall()]
            logger.info(f"Chat history retrieved for user {user_id}—their conversation is hotter than a CRE market boom! 🔥")
            return jsonify({"messages": messages})
        except Exception as e:
            logger.error(f"Failed to retrieve chat history for user {user_id}: {e}")
            return jsonify({"error": f"Failed to retrieve chat history: {str(e)}"}), 500

    return chat_bp
