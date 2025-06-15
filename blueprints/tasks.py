from flask import Blueprint, request, jsonify
from datetime import datetime
import json
import httpx

# Assuming app.py passes these through context or imports
from app import logger, cursor, conn, socketio

tasks_bp = Blueprint('tasks', __name__)
@token_required

@tasks_bp.route('/schedule', methods=['POST'])
def schedule_task(user_id):
    data = request.get_json()
    task_type = data.get('task_type')
    task_data = data.get('task_data')
    schedule_time = data.get('schedule_time')
    if not all([task_type, task_data, schedule_time]):
        return jsonify({"error": "Task type, task data, and schedule time are required—don’t leave me waiting! ⏰"}), 400

    try:
        cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, task_type, json.dumps(task_data), schedule_time, "pending"))
        conn.commit()
        logger.info(f"Task scheduled for user {user_id}: type={task_type}, time={schedule_time}—set to go off like a CRE deadline! 📅")
        return jsonify({"status": "Task scheduled—let’s keep the CRE momentum going! 🚀"})
    except Exception as e:
        logger.error(f"Failed to schedule task for user {user_id}: {e}")
@token_required
        return jsonify({"error": f"Failed to schedule task: {str(e)}"}), 500

@tasks_bp.route('', methods=['GET'])
def get_scheduled_tasks(user_id):
    try:
        cursor.execute("SELECT id, task_type, task_data, schedule_time, status FROM scheduled_tasks WHERE user_id = ?",
                       (user_id,))
        tasks = [{"id": row[0], "task_type": row[1], "task_data": json.loads(row[2]), "schedule_time": row[3], "status": row[4]}
                 for row in cursor.fetchall()]
        logger.info(f"Scheduled tasks retrieved for user {user_id}—their calendar is busier than a CRE broker! 🗓️")
        return jsonify({"tasks": tasks})
    except Exception as e:
@token_required
        logger.error(f"Failed to retrieve scheduled tasks for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve scheduled tasks: {str(e)}"}), 500

@tasks_bp.route('/trigger-for-contact', methods=['POST'])
def trigger_for_contact(user_id):
    data = request.get_json()
    contact_id = data.get('contact_id')
    trigger_type = data.get('trigger_type')  # e.g., "email", "sms", "call"
    schedule_time = data.get('schedule_time')  # ISO format
    message = data.get('message', '')

    if not all([contact_id, trigger_type, schedule_time]):
        return jsonify({"error": "Contact ID, trigger type, and schedule time are required—don’t leave me hanging! 🕒"}), 400

    # Validate trigger type
    valid_triggers = ["email", "sms", "call"]
    if trigger_type not in valid_triggers:
        return jsonify({"error": f"Invalid trigger type. Must be one of {valid_triggers}—let’s keep it CRE-friendly! 📧"}), 400

    # Fetch contact details from RealNex
    realnex_token = utils.get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return jsonify({"error": "RealNex token missing—can’t sync without the keys to the building! 🔑"}), 401

    try:
        with httpx.Client() as client:
            response = client.get(
                f"https://sync.realnex.com/api/v1/Crm/contact/{contact_id}",
                headers={'Authorization': f'Bearer {realnex_token}'}
            )
            response.raise_for_status()
            contact = response.json()
    except Exception as e:
        logger.error(f"Failed to fetch contact {contact_id} from RealNex for user {user_id}: {e}")
        return jsonify({"error": f"Failed to fetch contact: {str(e)}"}), 500

    # Prepare task data
    task_data = {
        "contact_id": contact_id,
        "fullName": contact.get("fullName", ""),
        "email": contact.get("email", ""),
        "phone": contact.get("mobile", ""),
        "trigger_type": trigger_type,
        "message": message
    }

    # Schedule the task
    try:
        cursor.execute("INSERT INTO scheduled_tasks (user_id, task_type, task_data, schedule_time, status) VALUES (?, ?, ?, ?, ?)",
                       (user_id, f"trigger_{trigger_type}", json.dumps(task_data), schedule_time, "pending"))
        conn.commit()

        # Log the activity
        utils.log_user_activity(user_id, "schedule_trigger",
                              {"contact_id": contact_id, "trigger_type": trigger_type, "schedule_time": schedule_time},
                              cursor, conn)

        # Emit WebSocket notification
        socketio.emit('task_scheduled', {
            'user_id': user_id,
            'message': f"Scheduled {trigger_type} trigger for {contact.get('fullName', 'contact')} at {schedule_time}"
        }, namespace='/chat')

        logger.info(f"Trigger scheduled for user {user_id}: {trigger_type} for contact {contact_id}—set to go off like a CRE alarm! ⏰")
        return jsonify({
            "status": f"{trigger_type.capitalize()} trigger scheduled for contact {contact_id}—ready to make waves! 🌊",
            "task_data": task_data,
            "schedule_time": schedule_time
        })
    except Exception as e:
        logger.error(f"Failed to schedule trigger for user {user_id}: {e}")
        return jsonify({"error": f"Failed to schedule trigger: {str(e)}"}), 500