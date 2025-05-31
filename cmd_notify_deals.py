from flask import jsonify
import re

from database import conn, cursor
from utils import log_user_activity

def handle_notify_deals(message, user_id, settings):
    if 'notify me of new deals over' in message:
        if not settings["deal_alerts_enabled"]:
            answer = "Deal alerts are disabled in settings. Enable them to set notifications! ⚙️"
            return jsonify({"answer": answer, "tts": answer})

        threshold = re.search(r'over\s*\$\s*([\d.]+)', message)
        threshold = float(threshold.group(1)) if threshold else None
        deal_type = "LeaseComp" if "leasecomp" in message else "SaleComp" if "salecomp" in message else "Any"

        if not threshold:
            answer = "Please specify a deal value threshold, e.g., 'notify me of new deals over $5000'. What’s the threshold? 🔔"
            return jsonify({"answer": answer, "tts": answer})

        cursor.execute("INSERT OR REPLACE INTO deal_alerts (user_id, threshold, deal_type) VALUES (?, ?, ?)",
                       (user_id, threshold, deal_type))
        conn.commit()

        answer = f"Got it! I’ll notify you of new {deal_type if deal_type != 'Any' else 'deals'} over ${threshold}. 🔔 Make sure your notification settings are enabled!"
        log_user_activity(user_id, "set_deal_alert", {"threshold": threshold, "deal_type": deal_type}, cursor, conn)
        return jsonify({"answer": answer, "tts": answer})

    return None
