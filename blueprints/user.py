from flask import Blueprint, request, jsonify
from db import logger, cursor, conn
from blueprints.auth import token_required

user_bp = Blueprint('user', __name__)


@user_bp.route('/settings', methods=['GET'])
@token_required
def get_settings(user_id):
    try:
        cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
        settings = cursor.fetchone()
        if settings:
            columns = [desc[0] for desc in cursor.description]
            settings_dict = dict(zip(columns, settings))
            logger.info(f"Settings retrieved for user {user_id}")
            return jsonify({"settings": settings_dict})
        return jsonify({"settings": {}})
    except Exception as e:
        logger.error(f"Failed to retrieve settings for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve settings: {str(e)}"}), 500


@user_bp.route('/settings', methods=['POST'])
@token_required
def update_settings(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No settings provided—don’t leave me empty-handed like an unleased space! 🏢"}), 400

    try:
        allowed_fields = [
            "language", "subject_generator_enabled", "deal_alerts_enabled",
            "email_notifications", "sms_notifications",
            "mailchimp_group_id", "mailchimp_api_key",
            "constant_contact_group_id",
            "realnex_group_id", "realnex_api_key",
            "apollo_group_id", "seamless_group_id", "zoominfo_group_id"
        ]
        settings = {field: data.get(field) for field in allowed_fields if field in data}

        if not settings:
            return jsonify({"error": "No valid settings provided—let’s fill that vacancy! 🏙️"}), 400

        columns = ', '.join(settings.keys())
        placeholders = ', '.join(['?'] * (len(settings) + 1))
        values = list(settings.values()) + [user_id]

        query = f"""
            INSERT INTO user_settings (user_id, {columns})
            VALUES ({placeholders})
            ON CONFLICT(user_id) DO UPDATE SET {', '.join([f"{k} = excluded.{k}" for k in settings.keys()])}
        """

        cursor.execute(query, values)
        conn.commit()

        logger.info(f"Settings updated for user {user_id}")
        return jsonify({"status": "Settings updated—your CRE game just leveled up! 🚀"})
    except Exception as e:
        logger.error(f"Failed to update settings for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update settings: {str(e)}"}), 500
