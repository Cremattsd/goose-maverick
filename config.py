import os
from dotenv import load_dotenv

# Load environment variables from a .env file (optional for local testing)
load_dotenv()

# OpenAI API Key (for ChatGPT AI Bot)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-fallback-key-if-needed")

# RealNex User Authentication Token
REALNEX_USER_TOKEN = os.getenv("REALNEX_USER_TOKEN", "")

# Base URL for RealNex API
REALNEX_API_BASE_URL = "https://sync.realnex.com/api"

# Function to check if API keys are available
def check_config():
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your-fallback-key-if-needed":
        print("⚠️ WARNING: OpenAI API key is missing. Set OPENAI_API_KEY in Render environment variables.")
    if not REALNEX_USER_TOKEN:
        print("⚠️ WARNING: RealNex User Token is missing. Users must enter their token to enable full functionality.")

# Run check when module is imported
check_config()
