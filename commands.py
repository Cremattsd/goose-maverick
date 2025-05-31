import json
import openai
from cmd_help import handle_help_phrases
from cmd_draft_email import handle_draft_email
from cmd_send_campaign import handle_send_campaign
from cmd_sync_data import handle_sync_data
from cmd_predict_deal import handle_predict_deal
from cmd_negotiate_deal import handle_negotiate_deal
from cmd_notify_deals import handle_notify_deals
from cmd_fallback import handle_fallback

from config import OPENAI_API_KEY
from database import conn, cursor
from utils import *

# Initialize OpenAI client
try:
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully.")
except Exception as e:
    logger.error(f"OpenAI client initialization failed: {e}")
    openai_client = None

# Global Mailchimp client
mailchimp = None

def register_commands(app, socketio):
    """Register the /ask endpoint for natural language commands."""
    @app.route('/ask', methods=['POST'])
    @token_required
    async def ask(user_id):
        """Handle natural language queries for CRE tasks."""
        data = request.json
        message = data.get('message', '').lower()

        cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        points = user_data[0] if user_data else 0
        email_credits = user_data[1] if user_data else 0
        has_msa = user_data[2] if user_data else 0

        settings = get_user_settings(user_id, cursor, conn)
        onboarding_steps = ["save_settings", "sync_crm_data", "send_realblast", "send_training_reminder"]
        completed_steps = []
        for step in onboarding_steps:
            cursor.execute("SELECT completed FROM user_onboarding WHERE user_id = ? AND step = ?", (user_id, step))
            result = cursor.fetchone()
            if result and result[0] == 1:
                completed_steps.append(step)

        original_message = message
        if settings["language"] != "en":
            if not openai_client:
                return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": f"Translate this {settings['language']} text to English."},
                        {"role": "user", "content": message}
                    ]
                )
                message = response.choices[0].message.content.lower()
                log_user_activity(user_id, "translate_message", {"from": settings["language"], "to": "en", "original": original_message, "translated": message}, cursor, conn)
            except Exception as e:
                logger.error(f"Translation failed: {e}")

        # Handle help/support requests
        result = handle_help_phrases(message, user_id)
        if result:
            return result

        # Handle email drafting commands
        result = handle_draft_email(message, user_id, settings, openai_client)
        if result:
            return result

        # Handle sending campaigns
        result = handle_send_campaign(message, user_id, data, points, email_credits, has_msa, settings, socketio, twilio_client)
        if result:
            return result

        # Handle syncing data
        result = handle_sync_data(message, user_id, data)
        if result:
            return result

        # Handle deal prediction
        result = handle_predict_deal(message, user_id, settings, twilio_client)
        if result:
            return result

        # Handle deal negotiation
        result = handle_negotiate_deal(message, user_id, openai_client)
        if result:
            return result

        # Handle deal notifications
        result = handle_notify_deals(message, user_id, settings)
        if result:
            return result

        # Fallback for unrecognized commands
        return handle_fallback()
