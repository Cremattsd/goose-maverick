import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class RealNexAPI:
    def __init__(self):
        self.api_key = os.getenv("REALNEX_API_TOKEN")  # Load API key from environment variables

    def is_api_enabled(self):
        """Check if API key is available"""
        return bool(self.api_key)

    def get_api_key(self):
        """Return the API key"""
        return self.api_key
