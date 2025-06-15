
from flask import Blueprint, redirect, request, session, jsonify, url_for
import datetime

email_auth_bp = Blueprint('email_auth', __name__)

# Mock endpoint to initiate OAuth flow
@email_auth_bp.route('/auth/email/connect')
def connect_email():
    provider = request.args.get("provider", "google")  # or 'outlook'
    session['oauth_state'] = 'mocked_state'
    # Normally redirect to provider's OAuth URL
    return jsonify({"message": f"Redirecting to {provider} OAuth", "url": f"/auth/email/callback?provider={provider}"}), 200

# Mock OAuth callback
@email_auth_bp.route('/auth/email/callback')
def email_callback():
    provider = request.args.get("provider", "google")
    # Normally handle token exchange here
    token_data = {
        "access_token": "mock_access_token",
        "refresh_token": "mock_refresh_token",
        "expires_at": (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat()
    }
    # Simulate user session
    user_id = session.get("user_id", "mock_user")
    print(f"[DEBUG] Saving token for {user_id} via {provider}")
    return jsonify({"message": f"{provider.title()} connected!", "tokens": token_data}), 200
