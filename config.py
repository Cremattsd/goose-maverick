import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask app config
SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key')

# Redis config
REDIS_HOST = os.getenv('REDIS_HOST', 'redis-11362.c265.us-east-1-2.ec2.redns.redis-cloud.com')
REDIS_PORT = int(os.getenv('REDIS_PORT', 11362))
REDIS_USERNAME = os.getenv('REDIS_USERNAME', 'default')
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_CA_PATH = os.getenv('REDIS_CA_PATH', 'certs/redis_ca.pem')

# SMTP config
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER', 'your-email@gmail.com')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', 'your-password')

# API base URLs and credentials
REALNEX_API_BASE = os.getenv('REALNEX_API_BASE', 'https://sync.realnex.com/api/v1/Crm')
TWILIO_SID = os.getenv('TWILIO_SID', 'your-twilio-sid')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', 'your-twilio-auth-token')
TWILIO_PHONE = os.getenv('TWILIO_PHONE', 'your-twilio-phone')
MAILCHIMP_SERVER_PREFIX = os.getenv('MAILCHIMP_SERVER_PREFIX', 'us1')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY', 'your-google-api-key')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'your-openai-api-key')
