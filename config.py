import os
from dotenv import load_dotenv

load_dotenv()

class RealNexAPI:
    def __init__(self):
        self.api_key = os.getenv("REALNEX_API_TOKEN")  # Load from environment variable
        if not self.api_key:
            print("⚠️ WARNING: No RealNex API token provided. Basic chat features will work, but data import & business card scanning require a token.")

    def is_api_enabled(self):
        """Check if API key is available"""
        return bool(self.api_key)
