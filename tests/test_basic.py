from flask import Flask
from routes.main_routes import main_routes

def test_index_route():
    app = Flask(__name__)
    app.register_blueprint(main_routes)
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    assert b"Goose Maverick API is live" in response.data
