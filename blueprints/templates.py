from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid

# Import shared resources
from db import logger, cursor, conn

# Import token_required decorator
from blueprints.auth import token_required

templates_bp = Blueprint('templates', __name__)

@templates_bp.route('', methods=['POST'])
@token_required
def create_template(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No template data provided—don’t leave me empty-handed like an unleased space! 🏢"}), 400

    try:
        template_id = str(uuid.uuid4())
        template_name = data.get('template_name', 'Untitled Template')
        template_content = data.get('template_content', '')
        template_type = data.get('template_type', 'email')

        # Insert template into database
        cursor.execute("INSERT INTO templates (id, user_id, template_name, template_content, template_type) VALUES (?, ?, ?, ?, ?)",
                       (template_id, user_id, template_name, template_content, template_type))
        conn.commit()

        logger.info(f"Template created for user {user_id}: {template_id}—they’re crafting CRE templates like a pro! 📝")
        return jsonify({"status": "Template created", "template_id": template_id})
    except Exception as e:
        logger.error(f"Failed to create template for user {user_id}: {e}")
        return jsonify({"error": f"Failed to create template: {str(e)}"}), 500

@templates_bp.route('', methods=['GET'])
@token_required
def get_templates(user_id):
    try:
        cursor.execute("SELECT id, template_name, template_content, template_type FROM templates WHERE user_id = ?", (user_id,))
        templates = [{"id": row[0], "template_name": row[1], "template_content": row[2], "template_type": row[3]} for row in cursor.fetchall()]
        logger.info(f"Templates retrieved for user {user_id}—their CRE templates are ready to shine! ✨")
        return jsonify({"templates": templates})
    except Exception as e:
        logger.error(f"Failed to retrieve templates for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve templates: {str(e)}"}), 500

@templates_bp.route('/<template_id>', methods=['PUT'])
@token_required
def update_template(user_id, template_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No update data provided—don’t leave me hanging like a vacant property! 🏢"}), 400

    try:
        cursor.execute("SELECT * FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Template not found—looks like this space is already leased! 🏙️"}), 404

        update_fields = []
        values = []
        if 'template_name' in data:
            update_fields.append("template_name = ?")
            values.append(data['template_name'])
        if 'template_content' in data:
            update_fields.append("template_content = ?")
            values.append(data['template_content'])
        if 'template_type' in data:
            update_fields.append("template_type = ?")
            values.append(data['template_type'])

        if not update_fields:
            return jsonify({"error": "No valid fields to update—let’s fill that vacancy! 🏙️"}), 400

        values.extend([template_id, user_id])
        query = f"UPDATE templates SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, values)
        conn.commit()

        logger.info(f"Template updated for user {user_id}: {template_id}—they’re keeping their CRE templates fresh! 🌟")
        return jsonify({"status": "Template updated"})
    except Exception as e:
        logger.error(f"Failed to update template for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update template: {str(e)}"}), 500

@templates_bp.route('/<template_id>', methods=['DELETE'])
@token_required
def delete_template(user_id, template_id):
    try:
        cursor.execute("SELECT * FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Template not found—looks like this space is already vacated! 🏙️"}), 404

        cursor.execute("DELETE FROM templates WHERE id = ? AND user_id = ?", (template_id, user_id))
        conn.commit()

        logger.info(f"Template deleted for user {user_id}: {template_id}—they’re clearing space for new CRE opportunities! 🏢")
        return jsonify({"status": "Template deleted"})
    except Exception as e:
        logger.error(f"Failed to delete template for user {user_id}: {e}")
        return jsonify({"error": f"Failed to delete template: {str(e)}"}), 500
