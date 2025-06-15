from flask import Blueprint, request, jsonify

# Assuming app.py passes these through context or imports
from app import logger, cursor, conn

webhooks_bp = Blueprint('webhooks', __name__)
@token_required

@webhooks_bp.route('/set', methods=['POST'])
def set_webhook(user_id):
    data = request.get_json()
    webhook_url = data.get('webhook_url')
    if not webhook_url:
        return jsonify({"error": "Webhook URL is required—don’t make me chase you like a late rent payment! 💸"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO webhooks (user_id, webhook_url) VALUES (?, ?)",
                       (user_id, webhook_url))
        conn.commit()
        logger.info(f"Webhook set for user {user_id}: {webhook_url}—ready to roll like a CRE deal on fire! 🔥")
        return jsonify({"status": "Webhook set—let’s keep the CRE notifications flowing! 📬"})
    except Exception as e:
        logger.error(f"Failed to set webhook for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set webhook: {str(e)}"}), 500