import json
import hashlib
from flask import Blueprint, request, jsonify
from datetime import datetime
import httpx
import uuid

from db import logger, cursor, conn
from utils import get_user_settings, get_token, log_user_activity, log_duplicate, sync_to_mailchimp, search_realnex_entities
from blueprints.auth import token_required

contacts_bp = Blueprint('contacts', __name__)

@contacts_bp.route('', methods=['POST'])
@token_required
def create_contact(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No contact data provided—don’t leave me empty-handed like an unleased space! 🏢"}), 400

    try:
        contact_id = str(uuid.uuid4())
        name = data.get('name', '')
        email = data.get('email', '')
        phone = data.get('phone', '')

        cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                       (contact_id, name, email, phone, user_id))
        conn.commit()

        log_user_activity(user_id, "create_contact", {"contact_id": contact_id}, cursor, conn)

        contact_data = {
            "id": contact_id,
            "name": name,
            "email": email,
            "phone": phone,
            "firstName": name.split()[0] if name else "",
            "lastName": " ".join(name.split()[1:]) if len(name.split()) > 1 else ""
        }

        sync_to_mailchimp(user_id, contact_data, cursor, conn)

        logger.info(f"Contact created for user {user_id}: {contact_id}—they’re building their CRE network like a pro! 🤝")
        return jsonify({"status": "Contact created", "contact_id": contact_id})
    except Exception as e:
        logger.error(f"Failed to create contact for user {user_id}: {e}")
        return jsonify({"error": f"Failed to create contact: {str(e)}"}), 500

@contacts_bp.route('', methods=['GET'])
@token_required
def get_contacts(user_id):
    try:
        cursor.execute("SELECT id, name, email, phone FROM contacts WHERE user_id = ?", (user_id,))
        contacts = [{"id": row[0], "name": row[1], "email": row[2], "phone": row[3]} for row in cursor.fetchall()]
        logger.info(f"Contacts retrieved for user {user_id}—they’ve got a network hotter than a CRE market boom! 🔥")
        return jsonify({"contacts": contacts})
    except Exception as e:
        logger.error(f"Failed to retrieve contacts for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve contacts: {str(e)}"}), 500

@contacts_bp.route('/<contact_id>', methods=['PUT'])
@token_required
def update_contact(user_id, contact_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No update data provided—don’t leave me hanging like a vacant property! 🏢"}), 400

    try:
        cursor.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Contact not found—looks like this space is already leased! 🏙️"}), 404

        name = data.get('name')
        email = data.get('email')
        phone = data.get('phone')

        update_fields = []
        values = []
        if name is not None:
            update_fields.append("name = ?")
            values.append(name)
        if email is not None:
            update_fields.append("email = ?")
            values.append(email)
        if phone is not None:
            update_fields.append("phone = ?")
            values.append(phone)

        if not update_fields:
            return jsonify({"error": "No valid fields to update—let’s fill that vacancy! 🏙️"}), 400

        values.extend([contact_id, user_id])
        query = f"UPDATE contacts SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, values)
        conn.commit()

        log_user_activity(user_id, "update_contact", {"contact_id": contact_id}, cursor, conn)

        cursor.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        contact = cursor.fetchone()
        contact_data = {
            "id": contact[0],
            "name": contact[1],
            "email": contact[2],
            "phone": contact[3],
            "firstName": contact[1].split()[0] if contact[1] else "",
            "lastName": " ".join(contact[1].split()[1:]) if len(contact[1].split()) > 1 else ""
        }

        sync_to_mailchimp(user_id, contact_data, cursor, conn)

        logger.info(f"Contact updated for user {user_id}: {contact_id}—they’re keeping their CRE network fresh! 🌟")
        return jsonify({"status": "Contact updated"})
    except Exception as e:
        logger.error(f"Failed to update contact for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update contact: {str(e)}"}), 500

@contacts_bp.route('/<contact_id>', methods=['DELETE'])
@token_required
def delete_contact(user_id, contact_id):
    try:
        cursor.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Contact not found—looks like this space is already vacated! 🏙️"}), 404

        cursor.execute("DELETE FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        conn.commit()

        log_user_activity(user_id, "delete_contact", {"contact_id": contact_id}, cursor, conn)
        logger.info(f"Contact deleted for user {user_id}: {contact_id}—they’re clearing space for new CRE opportunities! 🏢")
        return jsonify({"status": "Contact deleted"})
    except Exception as e:
        logger.error(f"Failed to delete contact for user {user_id}: {e}")
        return jsonify({"error": f"Failed to delete contact: {str(e)}"}), 500

@contacts_bp.route('/upload-file', methods=['POST'])
@token_required
def upload_file(user_id):
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded—don’t leave me empty like an unleased property! 🏢"}), 400

    file = request.files['file']
    try:
        contact_data = {
            "id": str(uuid.uuid4()),
            "name": "John Doe",
            "email": "john.doe@example.com",
            "phone": "123-456-7890",
            "firstName": "John",
            "lastName": "Doe"
        }

        contact_hash = hashlib.md5(json.dumps(contact_data, sort_keys=True).encode()).hexdigest()
        cursor.execute("SELECT * FROM duplicates_log WHERE contact_hash = ? AND user_id = ?",
                       (contact_hash, user_id))
        if cursor.fetchone():
            log_duplicate(user_id, contact_data, "contact", cursor, conn)
            return jsonify({"status": "Duplicate contact detected—already leased this space! 🏙️"})

        cursor.execute("INSERT INTO contacts (id, name, email, phone, user_id) VALUES (?, ?, ?, ?, ?)",
                       (contact_data["id"], contact_data["name"], contact_data["email"],
                        contact_data["phone"], user_id))
        conn.commit()

        sync_to_mailchimp(user_id, contact_data, cursor, conn)
        log_user_activity(user_id, "upload_contact_file", {"contact_id": contact_data["id"]}, cursor, conn)
        logger.info(f"File uploaded and contact created for user {user_id}: {contact_data['id']}—they’re filling their CRE pipeline! 📈")
        return jsonify({"status": "File processed", "contact_id": contact_data["id"]})
    except Exception as e:
        logger.error(f"Failed to process file upload for user {user_id}: {e}")
        return jsonify({"error": f"Failed to process file: {str(e)}"}), 500

@contacts_bp.route('/realnex', methods=['GET'])
@token_required
def search_realnex(user_id):
    query_params = request.args.to_dict()
    try:
        entities = search_realnex_entities(user_id, "contacts", query_params, cursor)
        logger.info(f"RealNex contacts retrieved for user {user_id}—they’re syncing like a CRE pro! 🔄")
        return jsonify({"entities": entities})
    except Exception as e:
        logger.error(f"Failed to search RealNex contacts for user {user_id}: {e}")
        return jsonify({"error": f"Failed to search RealNex: {str(e)}"}), 500
