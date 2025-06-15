from blueprints import auth

def test_auth_blueprint_exists():
    assert auth.bp is not None