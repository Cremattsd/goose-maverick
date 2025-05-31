from flask import jsonify
import re
from datetime import datetime
import base64
from email.mime.text import MIMEText
import smtplib
from sklearn.linear_model import LinearRegression

from config import *
from database import conn, cursor
from utils import *

def handle_predict_deal(message, user_id, settings, twilio_client):
    if 'predict deal' in message:
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
        sq_ft = None
        if 'square footage' in message or 'sq ft' in message:
            sq_ft = re.search(r'\d+', message)
            sq_ft = int(sq_ft.group()) if sq_ft else None

        if not deal_type or not sq_ft:
            answer = "To predict a deal, I need the deal type (LeaseComp or SaleComp) and square footage. Say something like 'predict deal for LeaseComp with 5000 sq ft'. What’s the deal type and square footage? 🔮"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex", cursor)
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to predict a deal. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        historical_data = await get_realnex_data(user_id, f"{deal_type}s", cursor)
        if not historical_data:
            answer = "No historical data available for prediction."
            return jsonify({"answer": answer, "tts": answer})

        X = []
        y = []
        prediction = 0
        if deal_type == "LeaseComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("rent_month", 0))
            model = LinearRegression()
            model.fit(X, y)
            prediction = model.predict([[sq_ft]])[0]
            answer = f"Predicted rent for {sq_ft} sq ft: ${prediction:.2f}/month. 🔮"
            chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type, cursor, conn)
            chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
            answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
            cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                           (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
            conn.commit()
            log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction}, cursor, conn)
            tts = f"Predicted rent for {sq_ft} square feet: ${prediction:.2f} per month."
        elif deal_type == "SaleComp":
            for item in historical_data:
                X.append([item.get("sq_ft", 0)])
                y.append(item.get("sale_price", 0))
            model = LinearRegression()
            model.fit(X, y)
            prediction = model.predict([[sq_ft]])[0]
            answer = f"Predicted sale price for {sq_ft} sq ft: ${prediction:.2f}. 🔮"
            chart_output = generate_deal_trend_chart(user_id, historical_data, deal_type, cursor, conn)
            chart_base64 = base64.b64encode(chart_output.read()).decode('utf-8')
            answer += f"\nTrend chart: data:image/png;base64,{chart_base64}"
            cursor.execute("INSERT OR IGNORE INTO deals (id, amount, close_date, user_id) VALUES (?, ?, ?, ?)",
                           (f"deal_{datetime.now().isoformat()}", prediction, datetime.now().strftime('%Y-%m-%d'), user_id))
            conn.commit()
            log_user_activity(user_id, "predict_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "prediction": prediction}, cursor, conn)
            tts = f"Predicted sale price for {sq_ft} square feet: ${prediction:.2f}."

        cursor.execute("SELECT threshold, deal_type FROM deal_alerts WHERE user_id = ?", (user_id,))
        alert = cursor.fetchone()
        if alert:
            threshold, alert_deal_type = alert
            if (alert_deal_type == "Any" or alert_deal_type == deal_type) and prediction > threshold:
                cursor.execute("SELECT webhook_url FROM webhooks WHERE user_id = ?", (user_id,))
                webhook = cursor.fetchone()
                if webhook:
                    webhook_url = webhook[0]
                    alert_data = {
                        "user_id": user_id,
                        "deal_type": deal_type,
                        "prediction": prediction,
                        "threshold": threshold,
                        "message": f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}."
                    }
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(webhook_url, json=alert_data)
                            log_user_activity(user_id, "trigger_webhook", {"webhook_url": webhook_url, "data": alert_data}, cursor, conn)
                        except Exception as e:
                            logger.error(f"Failed to trigger webhook: {str(e)}")
                if settings["sms_notifications"] and twilio_client:
                    twilio_client.messages.create(
                        body=f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.",
                        from_=TWILIO_PHONE,
                        to="+1234567890"
                    )
                if settings["email_notifications"]:
                    msg = MIMEText(f"New {deal_type} deal predicted: ${prediction:.2f} exceeds your threshold of ${threshold}.")
                    msg['Subject'] = "Deal Alert Notification"
                    msg['From'] = SMTP_USER
                    msg['To'] = "user@example.com"
                    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                        server.starttls()
                        server.login(SMTP_USER, SMTP_PASSWORD)
                        server.sendmail(SMTP_USER, "user@example.com", msg.as_string())

        return jsonify({"answer": answer, "tts": tts})

    return None
