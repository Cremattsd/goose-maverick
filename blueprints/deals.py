from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid

from db import logger, cursor, conn
from blueprints.auth import token_required

deals_bp = Blueprint('deals', __name__)

def init_socketio(socketio):
    @socketio.on('deal_update', namespace='/deals')
    def handle_deal_update(data):
        user_id = data.get('user_id')
        deal_id = data.get('deal_id')
        if user_id and deal_id:
            logger.info(f"Deal update received for user {user_id}, deal {deal_id}")
            socketio.emit('deal_updated', {
                "deal_id": deal_id,
                "status": "updated"
            }, namespace='/deals', room=user_id)

@deals_bp.route('', methods=['POST'])
@token_required
def create_deal(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No deal data provided"}), 400
    try:
        deal_id = str(uuid.uuid4())
        amount = data.get('amount', 0)
        close_date = data.get('close_date', datetime.now().isoformat())
        sq_ft = data.get('sq_ft', 0)
        rent_month = data.get('rent_month', 0)
        sale_price = data.get('sale_price', 0)
        deal_type = data.get('deal_type', 'lease')

        cursor.execute("""
            INSERT INTO deals (id, amount, close_date, user_id, sq_ft, rent_month, sale_price, deal_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (deal_id, amount, close_date, user_id, sq_ft, rent_month, sale_price, deal_type))
        conn.commit()

        logger.info(f"Deal created for user {user_id}: {deal_id}")
        return jsonify({"status": "Deal created", "deal_id": deal_id})
    except Exception as e:
        logger.error(f"Failed to create deal for user {user_id}: {e}")
        return jsonify({"error": f"Failed to create deal: {str(e)}"}), 500

@deals_bp.route('', methods=['GET'])
@token_required
def get_deals(user_id):
    try:
        cursor.execute("""
            SELECT id, amount, close_date, sq_ft, rent_month, sale_price, deal_type
            FROM deals WHERE user_id = ?
        """, (user_id,))
        deals = [{"id": row[0], "amount": row[1], "close_date": row[2], "sq_ft": row[3],
                  "rent_month": row[4], "sale_price": row[5], "deal_type": row[6]} for row in cursor.fetchall()]
        logger.info(f"Deals retrieved for user {user_id}")
        return jsonify({"deals": deals})
    except Exception as e:
        logger.error(f"Failed to retrieve deals for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve deals: {str(e)}"}), 500

@deals_bp.route('/<deal_id>', methods=['PUT'])
@token_required
def update_deal(user_id, deal_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No update data provided"}), 400
    try:
        cursor.execute("SELECT * FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Deal not found"}), 404

        update_fields = []
        values = []

        for field in ['amount', 'close_date', 'sq_ft', 'rent_month', 'sale_price', 'deal_type']:
            if field in data:
                update_fields.append(f"{field} = ?")
                values.append(data[field])

        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400

        values.extend([deal_id, user_id])
        query = f"UPDATE deals SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, values)
        conn.commit()

        logger.info(f"Deal updated for user {user_id}: {deal_id}")
        return jsonify({"status": "Deal updated"})
    except Exception as e:
        logger.error(f"Failed to update deal for user {user_id}: {e}")
        return jsonify({"error": f"Failed to update deal: {str(e)}"}), 500

@deals_bp.route('/<deal_id>', methods=['DELETE'])
@token_required
def delete_deal(user_id, deal_id):
    try:
        cursor.execute("SELECT * FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Deal not found"}), 404

        cursor.execute("DELETE FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        conn.commit()

        logger.info(f"Deal deleted for user {user_id}: {deal_id}")
        return jsonify({"status": "Deal deleted"})
    except Exception as e:
        logger.error(f"Failed to delete deal for user {user_id}: {e}")
        return jsonify({"error": f"Failed to delete deal: {str(e)}"}), 500
