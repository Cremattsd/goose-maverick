from flask import Blueprint, request, jsonify, send_file
from fpdf import FPDF
from io import BytesIO
import json

from app import logger, cursor, conn
from blueprints.auth import token_required

reports_bp = Blueprint('reports', __name__)

def generate_pdf_report(user_id, data, report_title):
    """Generate a PDF report from given data—like a CRE report that seals the deal! 📜"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=report_title, ln=True, align='C')
    pdf.ln(10)

    for key, value in data.items():
        pdf.cell(200, 10, txt=f"{key}: {value}", ln=True)

    pdf_output = BytesIO()
    pdf.output(pdf_output, 'F')
    pdf_output.seek(0)
    return pdf_output

@reports_bp.route('/generate', methods=['POST'])
@token_required
def generate_report(user_id):
    data = request.get_json()
    report_type = data.get('report_type')
    if not report_type:
        return jsonify({"error": "Report type is required—don’t leave me guessing like a CRE appraisal! 📊"}), 400

    try:
        if report_type == "duplicates":
            cursor.execute("SELECT contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ?",
                           (user_id,))
            duplicates = [{"contact_hash": row[0], "contact_data": json.loads(row[1]), "timestamp": row[2]}
                          for row in cursor.fetchall()]
            pdf = generate_pdf_report(user_id, {"Duplicates Found": len(duplicates)}, "Duplicates Report")
            logger.info(f"Duplicates report generated for user {user_id}—cleaning up like a pro! 🧹")
            return send_file(pdf, as_attachment=True, download_name="duplicates_report.pdf", mimetype='application/pdf')

        elif report_type == "activity":
            cursor.execute("SELECT action, details, timestamp FROM user_activity_log WHERE user_id = ?",
                           (user_id,))
            activities = [{"action": row[0], "details": json.loads(row[1]), "timestamp": row[2]}
                          for row in cursor.fetchall()]
            pdf = generate_pdf_report(user_id, {"Total Activities": len(activities)}, "Activity Report")
            logger.info(f"Activity report generated for user {user_id}—their moves are documented! 📝")
            return send_file(pdf, as_attachment=True, download_name="activity_report.pdf", mimetype='application/pdf')

        else:
            return jsonify({"error": "Unsupported report type—let’s stick to the CRE classics! 📜"}), 400

    except Exception as e:
        logger.error(f"Failed to generate report for user {user_id}: {e}")
        return jsonify({"error": f"Failed to generate report: {str(e)}"}), 500

@reports_bp.route('/duplicates-log', methods=['GET'])
@token_required
def get_duplicates_log(user_id):
    try:
        cursor.execute("SELECT id, contact_hash, contact_data, timestamp FROM duplicates_log WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        duplicates = [{"id": row[0], "contact_hash": row[1], "contact_data": json.loads(row[2]), "timestamp": row[3]}
                      for row in cursor.fetchall()]
        logger.info(f"Duplicates log retrieved for user {user_id}—cleaning up faster than a property manager! 🧹")
        return jsonify({"duplicates": duplicates})
    except Exception as e:
        logger.error(f"Failed to retrieve duplicates log for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve duplicates log: {str(e)}"}), 500

@reports_bp.route('/health-history', methods=['GET'])
@token_required
def get_health_history(user_id):
    try:
        cursor.execute("SELECT contact_id, email_health_score, phone_health_score, timestamp FROM health_history WHERE user_id = ? ORDER BY timestamp DESC",
                       (user_id,))
        history = [{"contact_id": row[0], "email_health_score": row[1], "phone_health_score": row[2], "timestamp": row[3]}
                   for row in cursor.fetchall()]
        logger.info(f"Health history retrieved for user {user_id}—their contacts are in top shape! 🩺")
        return jsonify({"health_history": history})
    except Exception as e:
        logger.error(f"Failed to retrieve health history for user {user_id}: {e}")
        return jsonify({"error": f"Failed to retrieve health history: {str(e)}"}), 500
