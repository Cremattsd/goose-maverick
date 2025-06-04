from flask import Blueprint, request, jsonify

# Assuming app.py passes these through context or imports
from app import logger, cursor, conn

templates_bp = Blueprint('templates', __name__)

@templates_bp.route('/email', methods=['POST'])
def save_email_template(user_id):
    data = request.get_json()
    template_name = data.get('template_name')
    subject = data.get('subject')
    body = data.get('body')
    if not all([template_name, subject, body]):
        return jsonify({"error": "Template name, subject, and body are required—don’t leave my inbox empty! 📧"}), 400

    try:
        cursor.execute("INSERT INTO email_templates (user_id, template_name, subject, body) VALUES (?, ?, ?, ?)",
                       (user_id, template_name, subject, body))
        conn.commit()
        logger.info(f"Email template saved for user {user_id}: {template_name}—ready to send some CRE magic! ✨")
        return jsonify({"status": "Email template saved—your CRE emails are about to shine! 🌟"})
    except Exception as e:
        logger.error(f"Failed to save email template for user {user_id}: {e}")
        return jsonify({"error": f"Failed to save email template: {str(e)}"}), 500

@templates_bp.route('/email', methods=['GET'])
def get_email_templates(user_id):
    try:
        cursor.execute("SELECT id, template_name, subject, body FROM email_templates WHERE user_id = ?",
                       (user_id,))
        templates = [{"id": row[0], "template_name": row[1], "subject": row[2], "body": row[3]}
                     for row in cursor.fetchall()]
        logger.info(f"Email templates retrieved for user {user_id}—their inbox game is strong! 📬")
        return jsonify({"templates": templates})
    except Exception as e:
        logger.error(f"Failed to retrieve email templates for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve email templates: {str(e)}"}), 500
