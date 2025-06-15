from flask import Flask
from routes.main_routes import main_routes  # ✅ Fixed: import the Blueprint instance, not the module

app = Flask(__name__)
app.register_blueprint(main_routes)

if __name__ == '__main__':
    app.run(debug=True)
