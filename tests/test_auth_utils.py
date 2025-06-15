
import jwt
from flask import Flask, jsonify
from auth_utils import token_required

def test_token_required_decorator():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-secret'
@token_required

    @app.route("/protected")
    @token_required
    def protected(user_id):
        return jsonify({"user": user_id})

    client = app.test_client()

    # Generate valid token
    token = jwt.encode({"user_id": "abc123"}, app.config['SECRET_KEY'], algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/protected", headers=headers)

    assert response.status_code == 200
    assert response.json["user"] == "abc123"