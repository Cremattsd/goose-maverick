from flask import jsonify
import re

from config import *
from database import conn, cursor
from utils import *

def handle_negotiate_deal(message, user_id, openai_client):
    if 'negotiate deal' in message:
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else None
        sq_ft = None
        offered_value = None
        if 'square footage' in message or 'sq ft' in message:
            sq_ft = re.search(r'square footage\s*(\d+)|sq ft\s*(\d+)', message)
            sq_ft = int(sq_ft.group(1) or sq_ft.group(2)) if sq_ft else None
        if 'offered' in message:
            offered_value = re.search(r'offered\s*\$\s*([\d.]+)', message)
            offered_value = float(offered_value.group(1)) if offered_value else None

        if not deal_type or not sq_ft or not offered_value:
            answer = "To negotiate a deal, I need the deal type (LeaseComp or SaleComp), square footage, and offered value. Say something like 'negotiate deal for LeaseComp with 5000 sq ft offered $5000'. What’s the deal type, square footage, and offered value? 🤝"
            return jsonify({"answer": answer, "tts": answer})

        token = get_token(user_id, "realnex", cursor)
        if not token:
            answer = "Please fetch your RealNex JWT token in Settings to negotiate a deal. 🔑"
            return jsonify({"answer": answer, "tts": answer})

        if not openai_client:
            return jsonify({"error": "OpenAI client not initialized. Check server logs for details."}), 500

        historical_data = await get_realnex_data(user_id, f"{deal_type}s", cursor)
        if not historical_data:
            answer = "No historical data available for negotiation."
            return jsonify({"answer": answer, "tts": answer})

        prompt = (
            f"You are a commercial real estate negotiation expert. Based on the following historical {deal_type} data, "
            f"suggest a counteroffer for a property with {sq_ft} square feet, where the offered value is ${offered_value} "
            f"({'per month' if deal_type == 'LeaseComp' else 'total'}). Historical data (square footage, value):\n"
        )
        for item in historical_data:
            sq_ft_value = item.get("sq_ft", 0)
            value = item.get("rent_month", 0) if deal_type == "LeaseComp" else item.get("sale_price", 0)
            prompt += f"- {sq_ft_value} sq ft: ${value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
        prompt += "Provide a counteroffer with a confidence score (0-100) and a brief explanation."

        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a commercial real estate negotiation expert."},
                    {"role": "user", "content": prompt}
                ]
            )
            ai_response = response.choices[0].message.content

            counteroffer_match = re.search(r'Counteroffer: \$([\d.]+)', ai_response)
            confidence_match = re.search(r'Confidence: (\d+)%', ai_response)
            explanation_match = re.search(r'Explanation: (.*?)(?:\n|$)', ai_response)

            counteroffer = float(counteroffer_match.group(1)) if counteroffer_match else offered_value * 1.1
            confidence = int(confidence_match.group(1)) if confidence_match else 75
            explanation = explanation_match.group(1) if explanation_match else "Based on historical data trends."

            answer = (
                f"Negotiation Suggestion for {deal_type}:\n"
                f"Offered: ${offered_value} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                f"Counteroffer: ${round(counteroffer, 2)} {'per month' if deal_type == 'LeaseComp' else 'total'}\n"
                f"Confidence: {confidence}%\n"
                f"Explanation: {explanation}\n"
                f"Ready to close this deal? 🤝"
            )
            log_user_activity(user_id, "negotiate_deal", {"deal_type": deal_type, "sq_ft": sq_ft, "offered_value": offered_value, "counteroffer": counteroffer}, cursor, conn)
            return jsonify({"answer": answer, "tts": answer})
        except Exception as e:
            answer = f"Failed to negotiate deal: {str(e)}. Try again."
            return jsonify({"answer": answer, "tts": answer})

    return None
