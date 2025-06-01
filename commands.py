import re
from .cmd_help import handle_help
from .cmd_draft_email import handle_draft_email
from .cmd_send_campaign import handle_send_campaign
from .cmd_sync_data import handle_sync_data
from .cmd_predict_deal import handle_predict_deal
from .cmd_negotiate_deal import handle_negotiate_deal
from .cmd_notify_deals import handle_notify_deals
from .cmd_realnex_query import handle_realnex_query
from .cmd_fallback import handle_fallback
from twilio.rest import Client as TwilioClient
from mailchimp_marketing import Client as MailchimpClient
from .config import TWILIO_SID, TWILIO_AUTH_TOKEN

def register_commands(app, socketio):
    # Initialize Twilio and Mailchimp clients
    try:
        twilio_client = TwilioClient(TWILIO_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        print(f"Twilio client initialization failed: {e}")
        twilio_client = None

    mailchimp_client = MailchimpClient()

    @app.route('/ask', methods=['POST'])
    def ask():
        data = request.json
        query = data.get('query', '').lower().strip()
        user_id = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not user_id:
            user_id = 'default'

        if not query:
            return jsonify({"response": "Please provide a query."})

        # Command routing
        if re.match(r'help', query):
            response = handle_help(query, user_id, cursor, conn)
        elif re.match(r'draft an email', query):
            response = handle_draft_email(query, user_id, cursor, conn)
        elif re.match(r'send (realblast|mailchimp)', query):
            response = handle_send_campaign(query, user_id, cursor, conn, twilio_client, mailchimp_client)
        elif re.match(r'sync (crm|contacts|deals|all)', query):
            response = handle_sync_data(query, user_id, cursor, conn)
        elif re.match(r'predict deal', query):
            response = handle_predict_deal(query, user_id, cursor, conn, twilio_client)
        elif re.match(r'negotiate deal', query):
            response = handle_negotiate_deal(query, user_id, cursor, conn)
        elif re.match(r'notify deals', query):
            response = handle_notify_deals(query, user_id, cursor, conn)
        elif re.match(r'realnex (.*)', query):
            response = handle_realnex_query(query, user_id, cursor, conn)
        else:
            response = handle_fallback(query, user_id, cursor, conn)

        return jsonify({"response": response})

    @socketio.on('message')
    def handle_message(data):
        query = data.get('message', '').lower().strip()
        user_id = data.get('user_id', 'default')

        if not query:
            socketio.emit('response', {"response": "Please provide a query."}, room=user_id)
            return

        # Command routing (same as above)
        if re.match(r'help', query):
            response = handle_help(query, user_id, cursor, conn)
        elif re.match(r'draft an email', query):
            response = handle_draft_email(query, user_id, cursor, conn)
        elif re.match(r'send (realblast|mailchimp)', query):
            response = handle_send_campaign(query, user_id, cursor, conn, twilio_client, mailchimp_client)
        elif re.match(r'sync (crm|contacts|deals|all)', query):
            response = handle_sync_data(query, user_id, cursor, conn)
        elif re.match(r'predict deal', query):
            response = handle_predict_deal(query, user_id, cursor, conn, twilio_client)
        elif re.match(r'negotiate deal', query):
            response = handle_negotiate_deal(query, user_id, cursor, conn)
        elif re.match(r'notify deals', query):
            response = handle_notify_deals(query, user_id, cursor, conn)
        elif re.match(r'realnex (.*)', query):
            response = handle_realnex_query(query, user_id, cursor, conn)
        else:
            response = handle_fallback(query, user_id, cursor, conn)

        socketio.emit('response', {"response": response}, room=user_id)
