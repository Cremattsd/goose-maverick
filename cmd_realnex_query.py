import re
import logging
import httpx
from .utils import get_token, log_user_activity

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("chatbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def handle_realnex_query(query, user_id, cursor, conn):
    """Handle RealNex-related queries by fetching data from the API."""
    match = re.match(r'realnex (.*)', query, re.IGNORECASE)
    if not match:
        return "Invalid RealNex query. Use: 'realnex <query>'"

    realnex_query = match.group(1).lower().strip()
    realnex_token = get_token(user_id, "realnex", cursor)
    if not realnex_token:
        return "No RealNex token found. Please set it in settings."

    # Example queries: "realnex get recent deals", "realnex find contact John Doe"
    if "recent deals" in realnex_query:
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/deals",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    params={"limit": 5, "sort": "created_date_desc"}
                )
                response.raise_for_status()
                deals = response.json()
                if not deals:
                    return "No recent deals found in RealNex."
                deal_list = "\n".join([f"Deal ID: {deal['id']}, Amount: ${deal.get('amount', 'N/A')}, Date: {deal.get('created_date', 'N/A')}" for deal in deals])
                log_user_activity(user_id, "realnex_query", {"query": "recent deals"}, cursor, conn)
                return f"Recent RealNex Deals:\n{deal_list}"
        except Exception as e:
            logger.error(f"Failed to fetch RealNex deals: {e}")
            return f"Failed to fetch RealNex deals: {str(e)}"

    elif "find contact" in realnex_query:
        contact_name = realnex_query.replace("find contact", "").strip()
        try:
            with httpx.Client() as client:
                response = client.get(
                    "https://api.realnex.com/v1/contacts",
                    headers={'Authorization': f'Bearer {realnex_token}'},
                    params={"search": contact_name}
                )
                response.raise_for_status()
                contacts = response.json()
                if not contacts:
                    return f"No contacts found for '{contact_name}' in RealNex."
                contact_list = "\n".join([f"Name: {contact['name']}, Email: {contact.get('email', 'N/A')}" for contact in contacts])
                log_user_activity(user_id, "realnex_query", {"query": f"find contact {contact_name}"}, cursor, conn)
                return f"Contacts Found in RealNex:\n{contact_list}"
        except Exception as e:
            logger.error(f"Failed to fetch RealNex contacts: {e}")
            return f"Failed to fetch RealNex contacts: {str(e)}"

    else:
        return "Unsupported RealNex query. Try 'realnex get recent deals' or 'realnex find contact <name>'."
