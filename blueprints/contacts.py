from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, timedelta
import utils

# Assuming app.py passes these through context or imports
from app import logger, cursor, conn, socketio

deals_bp = Blueprint('deals', __name__)

@deals_bp.route('/trends', methods=['GET'])
def deal_trends_page(user_id):
    logger.info("Deal trends page accessed—let’s analyze the market like CRE pros! 📈")
    current_date = datetime.now().isoformat()
    historical_data = [
        {"sq_ft": 1000, "rent_month": 2000, "sale_price": 500000, "deal_type": "LeaseComp", "date": current_date},
        {"sq_ft": 2000, "rent_month": 3500, "sale_price": 750000, "deal_type": "LeaseComp", "date": current_date},
        {"sq_ft": 3000, "rent_month": 5000, "sale_price": 1000000, "deal_type": "SaleComp", "date": current_date},
        {"sq_ft": 4000, "rent_month": 6500, "sale_price": 1200000, "deal_type": "SaleComp", "date": current_date}
    ]
    lease_data = [item for item in historical_data if item["deal_type"] == "LeaseComp"]
    sale_data = [item for item in historical_data if item["deal_type"] == "SaleComp"]
    return render_template('deal_trends.html', lease_data=lease_data, sale_data=sale_data)

@deals_bp.route('/trends/<deal_type>', methods=['GET'])
def deal_trends(user_id, deal_type):
    """Generate deal trend data for the specified deal type."""
    valid_deal_types = ['LeaseComp', 'SaleComp']
    if deal_type not in valid_deal_types:
        logger.warning(f"Invalid deal type {deal_type} requested by user {user_id}")
        return jsonify({"error": f"Invalid deal type. Must be one of {valid_deal_types}—don’t try to invent new CRE terms! 📜"}), 400

    try:
        cursor.execute("SELECT sq_ft, rent_month, sale_price, date FROM deals WHERE user_id = ? AND deal_type = ?",
                       (user_id, deal_type))
        deals = [{"sq_ft": row[0], "rent_month": row[1], "sale_price": row[2], "date": row[3]} for row in cursor.fetchall()]
        
        if not deals:
            logger.info(f"No deals found for user {user_id} with deal type {deal_type}")
            return jsonify({"message": f"No {deal_type} deals found—time to close some CRE deals! 🏢"}), 200

        chart_data = utils.generate_deal_trend_chart(deals, deal_type)
        logger.info(f"Deal trends generated for user {user_id}: type={deal_type}")
        return jsonify({"chart_data": chart_data})
    except Exception as e:
        logger.error(f"Failed to generate deal trends for user {user_id}: {e}")
        return jsonify({"error": f"Failed to generate deal trends: {str(e)}"}), 500

@deals_bp.route('', methods=['GET'])
def get_deals(user_id):
    try:
        cursor.execute("SELECT id, amount, close_date FROM deals WHERE user_id = ?", (user_id,))
        deals = [{"id": row[0], "amount": row[1], "close_date": row[2]} for row in cursor.fetchall()]
        logger.info(f"Deals retrieved for user {user_id}—their portfolio is looking sweet! 🏢")
        return jsonify({"deals": deals})
    except Exception as e:
        logger.error(f"Failed to retrieve deals for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve deals: {str(e)}"}), 500

@deals_bp.route('/add', methods=['POST'])
def add_deal(user_id):
    data = request.get_json()
    deal_id = data.get('id')
    amount = data.get('amount')
    close_date = data.get('close_date')
    if not all([deal_id, amount, close_date]):
        return jsonify({"error": "Deal ID, amount, and close date are required—don’t leave me hanging like an unsigned lease! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                       (deal_id, amount, close_date, user_id))
        conn.commit()

        # Check deal alerts
        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        alert = cursor.fetchone()
        if alert and float(amount) >= float(alert[0]):
            socketio.emit('deal_alert', {
                'user_id': user_id,
                'message': f"Deal alert: New {alert[1]} deal of ${amount} (threshold: {alert[0]})",
                'deal_type': alert[1]
            }, namespace='/chat')

        logger.info(f"Deal added for user {user_id}: id={deal_id}, amount={amount}—time to pop the champagne! 🍾")
        return jsonify({"status": "Deal added—another win for the CRE team! 🏆"})
    except Exception as e:
        logger.error(f"Failed to add deal for user {user_id}: {e}")
        return jsonify({"error": f"Failed to add deal: {str(e)}"}), 500

@deals_bp.route('/alerts', methods=['GET'])
def get_deal_alerts(user_id):
    try:
        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            alert_data = {"threshold": result[0], "deal_type": result[1]}
        else:
            alert_data = {"threshold": 0, "deal_type": "none"}
        logger.info(f"Deal alerts retrieved for user {user_id}—keeping an eye on the CRE market! 👀")
        return jsonify(alert_data)
    except Exception as e:
        logger.error(f"Failed to retrieve deal alerts for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve deal alerts: {str(e)}"}), 500

@deals_bp.route('/set-alert', methods=['POST'])
def set_deal_alert(user_id):
    data = request.get_json()
    threshold = data.get('threshold')
    deal_type = data.get('deal_type')
    if threshold is None or not deal_type:
        return jsonify({"error": "Threshold and deal type are required—don’t leave me hanging like an unsigned lease! 📜"}), 400

    try:
        cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold, deal_type) VALUES (?, ?, ?)",
                       (user_id, float(threshold), deal_type))
        conn.commit()
        logger.info(f"Deal alert set for user {user_id}: threshold={threshold}, deal_type={deal_type}—they’re ready to catch big CRE deals! 🎣")
        return jsonify({"status": "Deal alert set—time to snag those deals! 🏢"})
    except Exception as e:
        logger.error(f"Failed to set deal alert for user {user_id}: {e}")
        return jsonify({"error": f"Failed to set deal alert: {str(e)}"}), 500
