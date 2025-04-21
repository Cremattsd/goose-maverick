from flask import Flask, render_template, request, jsonify, current_app
from flask_cors import CORS
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired
import requests
import sqlite3
import os
from dotenv import load_dotenv
import logging

# Initialize Flask app
app = Flask(__name__, static_folder='static')
CORS(app)

# Load environment variables
load_dotenv()
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'fallback-secret-key-for-dev-only')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize SQLite database
def init_db():
    os.makedirs('db', exist_ok=True)
    with sqlite3.connect('db/credentials.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                company_id TEXT
            )
        ''')
        conn.commit()
    logger.info("Successfully initialized SQLite database at db/credentials.db")

init_db()

# Form for snippet generation
class SnippetForm(FlaskForm):
    snippet_type = SelectField('Snippet Type', choices=[('contact', 'Contact Us'), ('listing', 'Listings + Contact Us')], validators=[DataRequired()])
    token = StringField('Token', validators=[DataRequired()])
    company_id = StringField('Company ID')
    submit = SubmitField('Generate Snippet')

# Validate RealNex API token
def validate_realnex_token(token, company_id=None):
    url = "https://api.realnex.com/v2/validate"  # Replace with actual endpoint
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"RealNex API response: {data}")
        return data
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error: {e}, Response: {response.text}")
        return None
    except requests.exceptions.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}, Response: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        return None

# Home route
@app.route('/')
def index():
    form = SnippetForm()
    return render_template('index.html', form=form)

# Snippet generation route
@app.route('/snippet', methods=['GET', 'POST'])
def snippet():
    form = SnippetForm()
    if request.method == 'POST':
        if form.validate_on_submit():
            token = form.token.data
            company_id = form.company_id.data if form.snippet_type.data == 'listing' else None
            snippet_type = form.snippet_type.data

            # Validate token with RealNex API
            api_response = validate_realnex_token(token, company_id)
            if not api_response:
                return render_template('snippet.html', form=form, error="Invalid token or API error", snippet_code="")

            # Store credentials in database
            with sqlite3.connect('db/credentials.db') as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT INTO credentials (token, company_id) VALUES (?, ?)', (token, company_id))
                conn.commit()

            # Generate iframe snippet
            iframe_url = f"{request.url_root}form?snippet_type={snippet_type}&token={token}"
            if company_id:
                iframe_url += f"&company_id={company_id}"
            snippet_code = f'<iframe src="{iframe_url}" width="100%" height="600" frameborder="0" style="border:0;"></iframe>'
            return render_template('snippet.html', form=form, snippet_code=snippet_code, error=None)
        else:
            return render_template('snippet.html', form=form, error="Form validation failed", snippet_code="")
    
    # GET request: show form
    snippet_type = request.args.get('snippet_type', 'contact')
    token = request.args.get('token', '')
    company_id = request.args.get('company_id', '')
    form.snippet_type.data = snippet_type
    form.token.data = token
    form.company_id.data = company_id
    return render_template('snippet.html', form=form, snippet_code="", error=None)

# Form rendering route (for iframe)
@app.route('/form')
def form():
    snippet_type = request.args.get('snippet_type', 'contact')
    token = request.args.get('token', '')
    company_id = request.args.get('company_id', '')
    
    # Validate token
    if not validate_realnex_token(token, company_id):
        return "Invalid token", 403
    
    return render_template('form.html', snippet_type=snippet_type, token=token, company_id=company_id)

if __name__ == '__main__':
    app.run(debug=True)
