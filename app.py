import os
from flask import Flask
from routes.main_routes import main_routes  # ✅ Correctly importing the Blueprint

app = Flask(__name__)
app.register_blueprint(main_routes)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # ✅ Use the PORT environment variable
    app.run(host="0.0.0.0", port=port)        # ✅ Bind to all interfaces
