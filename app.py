from flask import Flask, request, jsonify, render_template
import os

app = Flask(__name__)

# Store user tokens temporarily
user_tokens = {}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    user_token = request.form.get('api_token')
    uploaded_file = request.files.get('file')

    if not user_token:
        return jsonify({'status': 'error', 'message': 'No API token provided. Please enter your token before uploading.'})

    if not uploaded_file:
        return jsonify({'status': 'error', 'message': 'No file uploaded. Please select a file.'})

    # Store user token
    user_tokens['current_user'] = user_token

    # Save the file temporarily
    file_path = os.path.join('uploads', uploaded_file.filename)
    uploaded_file.save(file_path)

    # Provide summary and confirmation prompt
    file_size = os.path.getsize(file_path)
    file_summary = {
        'status': 'success',
        'message': f'File "{uploaded_file.filename}" ({file_size / 1024:.2f} KB) uploaded successfully.',
        'confirm_message': 'Do you want Goose to import this data into RealNex?',
        'file_name': uploaded_file.filename,
        'file_size': f'{file_size / 1024:.2f} KB'
    }
    
    return jsonify(file_summary)

@app.route('/confirm-import', methods=['POST'])
def confirm_import():
    user_token = user_tokens.get('current_user')
    
    if not user_token:
        return jsonify({'status': 'error', 'message': 'No API token found. Please enter your token before proceeding.'})

    file_name = request.json.get('file_name')

    if not file_name:
        return jsonify({'status': 'error', 'message': 'No file specified for import.'})

    # Simulate data import to RealNex
    import_status = {
        'status': 'success',
        'message': f'Goose successfully imported "{file_name}" into RealNex!',
        'token_used': user_token  # Display token usage for transparency
    }
    
    return jsonify(import_status)

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    app.run(debug=True)
