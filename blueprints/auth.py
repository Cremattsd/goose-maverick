# Final fixed versions of your blueprint files

# ========== blueprints/auth.py ==========
from auth_utils import token_required
import jwt
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, current_app
from db import logger, cursor, conn

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required—don’t leave me vacant! 🏢"}), 400
    try:
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        if not user:
            user_id = str(uuid.uuid4())
            created_at = datetime.now().isoformat()
            cursor.execute("INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
                           (user_id, email, created_at))
            conn.commit()
            logger.info(f"New user created: {user_id} with email {email}")
        else:
            user_id = user[0]
        token = jwt.encode({
            'user_id': user_id,
            'exp': datetime.utcnow() + timedelta(hours=24)
        }, current_app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({"token": token, "user_id": user_id})
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": f"Failed to login: {str(e)}"}), 500


# ========== blueprints/deals.py ==========
from flask import Blueprint, request, jsonify
from datetime import datetime
import uuid
from db import logger, cursor, conn
from blueprints.auth import token_required

deals_bp = Blueprint('deals', __name__)

@deals_bp.route('', methods=['POST'])
@token_required
def create_deal(user_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No deal data provided."}), 400
    try:
        deal_id = str(uuid.uuid4())
        amount = data.get('amount', 0)
        close_date = data.get('close_date', datetime.now().isoformat())
        sq_ft = data.get('sq_ft', 0)
        rent_month = data.get('rent_month', 0)
        sale_price = data.get('sale_price', 0)
        deal_type = data.get('deal_type', 'lease')
        cursor.execute("INSERT INTO deals (id, amount, close_date, user_id, sq_ft, rent_month, sale_price, deal_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (deal_id, amount, close_date, user_id, sq_ft, rent_month, sale_price, deal_type))
        conn.commit()
        return jsonify({"status": "Deal created", "deal_id": deal_id})
    except Exception as e:
        logger.error(f"Deal creation failed: {e}")
        return jsonify({"error": f"Failed to create deal: {str(e)}"}), 500

@deals_bp.route('', methods=['GET'])
@token_required
def get_deals(user_id):
    try:
        cursor.execute("SELECT id, amount, close_date, sq_ft, rent_month, sale_price, deal_type FROM deals WHERE user_id = ?", (user_id,))
        deals = [{"id": row[0], "amount": row[1], "close_date": row[2], "sq_ft": row[3], "rent_month": row[4], "sale_price": row[5], "deal_type": row[6]} for row in cursor.fetchall()]
        return jsonify({"deals": deals})
    except Exception as e:
        logger.error(f"Get deals failed: {e}")
        return jsonify({"error": f"Failed to retrieve deals: {str(e)}"}), 500

@deals_bp.route('/<deal_id>', methods=['PUT'])
@token_required
def update_deal(user_id, deal_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No update data provided."}), 400
    try:
        cursor.execute("SELECT * FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Deal not found."}), 404
        fields, values = [], []
        for field in ['amount', 'close_date', 'sq_ft', 'rent_month', 'sale_price', 'deal_type']:
            if field in data:
                fields.append(f"{field} = ?")
                values.append(data[field])
        if not fields:
            return jsonify({"error": "No valid fields to update."}), 400
        values += [deal_id, user_id]
        query = f"UPDATE deals SET {', '.join(fields)} WHERE id = ? AND user_id = ?"
        cursor.execute(query, values)
        conn.commit()
        return jsonify({"status": "Deal updated"})
    except Exception as e:
        logger.error(f"Update deal failed: {e}")
        return jsonify({"error": f"Failed to update deal: {str(e)}"}), 500

@deals_bp.route('/<deal_id>', methods=['DELETE'])
@token_required
def delete_deal(user_id, deal_id):
    try:
        cursor.execute("SELECT * FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "Deal not found."}), 404
        cursor.execute("DELETE FROM deals WHERE id = ? AND user_id = ?", (deal_id, user_id))
        conn.commit()
        return jsonify({"status": "Deal deleted"})
    except Exception as e:
        logger.error(f"Delete deal failed: {e}")
        return jsonify({"error": f"Failed to delete deal: {str(e)}"}), 500


# ========== blueprints/reports.py ==========
from flask import Blueprint, request, jsonify, send_file
from fpdf import FPDF
from io import BytesIO
import json
from db import logger, cursor, conn
from blueprints.auth import token_required

reports_bp = Blueprint('reports', __name__)

def generate_pdf_report(user_id, data, report_title):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=report_title, ln=True, align='C')
    pdf.ln(10)
    for key, value in data.items():
        pdf.cell(200, 10, txt=f"{key}: {value}", ln=True)
    output = BytesIO()
    pdf.output(output, 'F')
    output.seek(0)
    return output

@reports_bp.route('/generate', methods=['POST'])
@token_required
def generate_report(user_id):
    data = request.get_json()
    report_type = data.get('report_type')
    if not report_type:
        return jsonify({"error": "Report type is required."}), 400
    try:
        if report_type == "duplicates":
            cursor.execute("SELECT contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ?", (user_id,))
            duplicates = cursor.fetchall()
            pdf = generate_pdf_report(user_id, {"Duplicates Found": len(duplicates)}, "Duplicates Report")
            return send_file(pdf, as_attachment=True, download_name="duplicates_report.pdf", mimetype='application/pdf')
        elif report_type == "activity":
            cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ?", (user_id,))
            activities = cursor.fetchall()
            pdf = generate_pdf_report(user_id, {"Total Activities": len(activities)}, "Activity Report")
            return send_file(pdf, as_attachment=True, download_name="activity_report.pdf", mimetype='application/pdf')
        else:
            return jsonify({"error": "Unsupported report type."}), 400
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500

@reports_bp.route('/duplicates-log', methods=['GET'])
@token_required
def get_duplicates_log(user_id):
    try:
        cursor.execute("SELECT id, contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        duplicates = [{"id": row[0], "contact_hash": row[1], "contact_data": json.loads(row[2]), "timestamp": row[3]} for row in cursor.fetchall()]
        return jsonify({"duplicates": duplicates})
    except Exception as e:
        logger.error(f"Retrieve duplicates failed: {e}")
        return jsonify({"error": f"Failed to retrieve duplicates log: {str(e)}"}), 500

@reports_bp.route('/health-history', methods=['GET'])
@token_required
def get_health_history(user_id):
    try:
        cursor.execute("SELECT contact_id, email_health_score, phone_health_score, timestamp FROM health_history WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        history = [{"contact_id": row[0], "email_health_score": row[1], "phone_health_score": row[2], "timestamp": row[3]} for row in cursor.fetchall()]
        return jsonify({"health_history": history})
    except Exception as e:
        logger.error(f"Retrieve health history failed: {e}")
        return jsonify({"error": f"Failed to retrieve health history: {str(e)}"}), 500
