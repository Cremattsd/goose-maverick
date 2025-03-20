from flask import Flask, render_template, request, jsonify
import os
import openai
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Goose: Data Import Logic
def process_uploaded_file(file_path, user_token):
    if not user_token:
        return {"status": "error", "message": "No API token provided!"}
    
    file_type = file_path.split('.')[-1].upper()
    return {"status": "success", "message": f"Goose imported {file_type} file successfully."}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"})
    
    file = request.files['file']
    user_token = request.form.get('token')
    
    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"})
    
    if not user_token:
        return jsonify({"status": "error", "message": "API token is required!"})
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    
    response = process_uploaded_file(file_path, user_token)
    return jsonify(response)

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '').lower()
    bot_type = request.json.get('bot', 'Maverick')
    
    if bot_type == "Goose":
        return jsonify({"response": "Goose only imports files. Upload one below!"})
    
    response = "Maverick here! Let me assist with RealNex."
    if "realnex" in user_message:
        response = "RealNex is a powerful CRE platform with CRM, MarketPlace, and data sync tools."
    elif "help" in user_message:
        response = "Maverick can guide you on RealNex, and Goose imports your data. How can I assist?"
    
    return jsonify({"response": response})

if __name__ == '__main__':
    app.run(debug=True)
