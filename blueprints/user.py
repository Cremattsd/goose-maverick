from flask import Blueprint, request, jsonify, render_template
import utils

# Assuming app.py passes these through context or imports
from app import logger, cursor, conn

user_bp = Blueprint('user', __name__)

@user_bp.route('/dashboard', methods=['GET'])
def dashboard(user_id):
    logger.info("Duplicates dashboard page accessed—let’s clean up like a pro property manager! 🧹")
    return render_template('duplicates_dashboard.html')

@user_bp.route('/activity', methods=['GET'])
def activity_log_page(user_id):
    return render_template('activity.html')

@user_bp.route('/field-map', methods=['GET'])
def field_map(user_id):
    return render_template('field_map.html')

@user_bp.route('/scan', methods=['GET'])
def scan_page(user_id):
    return render_template('ocr.html')

@user_bp.route('/settings', methods=['GET'])
def settings_page(user_id):
    settings = utils.get_user_settings(user_id, cursor, conn)
    return render_template('settings.html', settings=settings)

@user_bp.route('/update-settings', methods=['POST'])
def update_settings(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided—don’t leave me empty like an unleased office! 🏢"}), 400

    try:
        cursor.execute('''INSERT OR REPLACE INTO user_settings (user_id, language, subject_generator_enabled, 
                          deal_alerts_enabled, email_notifications, sms_notifications, mailchimp_group_id, 
                          constant_contact_group_id, realnex_group_id, apollo_group_id, seamless_group_id, zoominfo_group_id)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (user_id, data.get('language', 'en'), int(data.get('subject_generator_enabled', 0)),
                        int(data.get('deal_alerts_enabled', 0)), int(data.get('email_notifications', 0)),
                        int(data.get('sms_notifications', 0)), data.get('mailchimp_group_id', ''),
                        data.get('constant_contact_group_id', ''), data.get('realnex_group_id', ''),
                        data.get('apollo_group_id', ''), data.get('seamless_group_id', ''), data.get('zoominfo_group_id', '')))
        conn.commit()
        logger.info(f"Settings updated for user {user_id}—tuned up like a CRE deal ready to close! 🔧")
        return jsonify({"status": "Settings updated—looking sharp! ✨"})
    except Exception as e:
        logger.error(f"Failed to update settings for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update settings: {str(e)}"}), 500

@user_bp.route('/points', methods=['GET'])
def get_points(user_id):
    try:
        cursor.execute("SELECT points, email_credits, has_msa FROM user_points WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            points_data = {"points": result[0], "email_credits": result[1], "has_msa": bool(result[2])}
        else:
            points_data = {"points": 0, "email_credits": 0, "has_msa": False}
            cursor.execute("INSERT INTO user_points (user_id, points, email_credits, has_msa) VALUES (?, ?, ?, ?)",
                           (user_id, 0, 0, 0))
            conn.commit()
        logger.info(f"Points retrieved for user {user_id}—their score is looking hot! 🔥")
        return jsonify(points_data)
    except Exception as e:
        logger.error(f"Failed to retrieve points for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve points: {str(e)}"}), 500

@user_bp.route('/update-points', methods=['POST'])
def update_points(user_id):
    data = request.get_json()
    points = data.get('points', 0)
    email_credits = data.get('email_credits', 0)
    has_msa = data.get('has_msa', False)

    try:
        cursor.execute("INSERT OR REPLACE INTO user_points (user_id, points, email_credits, has_msa) VALUES (?, ?, ?, ?)",
                       (user_id, points, email_credits, int(has_msa)))
        conn.commit()
        logger.info(f"Points updated for user {user_id}: points={points}, email_credits={email_credits}, has_msa={has_msa}—they’re climbing the CRE leaderboard! 📊")
        return jsonify({"status": "Points updated—your CRE game is strong! 💪"})
    except Exception as e:
        logger.error(f"Failed to update points for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update points: {str(e)}"}), 500

@user_bp.route('/onboarding-status', methods=['GET'])
def get_onboarding_status(user_id):
    try:
        cursor.execute("SELECT step, completed FROM user_onboarding WHERE user_id = ?", (user_id,))
        steps = cursor.fetchall()
        onboarding_status = {step: bool(completed) for step, completed in steps}
        logger.info(f"Onboarding status retrieved for user {user_id}—they’re navigating CRE like a pro! 🧭")
        return jsonify(onboarding_status)
    except Exception as e:
        logger.error(f"Failed to retrieve onboarding status for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve onboarding status: {str(e)}"}), 500

@user_bp.route('/update-onboarding', methods=['POST'])
def update_onboarding(user_id):
    data = request.get_json()
    step = data.get('step')
    completed = data.get('completed', False)
    if not step:
        return jsonify({"error": "Step is required—don’t skip steps like a rushed lease signing! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO user_onboarding (user_id, step, completed) VALUES (?, ?, ?)",
                       (user_id, step, int(completed)))
        conn.commit()
        logger.info(f"Onboarding step {step} updated for user {user_id}: completed={completed}—they’re one step closer to CRE mastery! 🏆")
        return jsonify({"status": f"Onboarding step {step} updated—nice progress! 🚀"})
    except Exception as e:
        logger.error(f"Failed to update onboarding for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update onboarding: {str(e)}"}), 500

@user_bp.route('/activity-log', methods=['GET'])
def get_activity_log(user_id):
    try:
        cursor.execute("SELECT id, action, details, timestamp FROM user_activity_log WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        activities = [{"id": row[0], "action": row[1], "details": json.loads(row[2]), "timestamp": row[3]}
                      for row in cursor.fetchall()]
        logger.info(f"Activity log retrieved for user {user_id}—their moves are smoother than a CRE deal closing! 🏢")
        return jsonify({"activities": activities})
    except Exception as e:
        logger.error(f"Failed to retrieve activity log for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve activity log: {str(e)}"}), 500
