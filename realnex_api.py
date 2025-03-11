import requests
import logging

logger = logging.getLogger(__name__)

class RealNexAPI:
    def __init__(self, api_key):
        self.base_url = "https://sync.realnex.com/api"
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def authenticate(self):
        url = f"{self.base_url}/Client"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return {"error": response.json().get("message", response.text)}
        except Exception as e:
            return {"error": str(e)}

    def upload_file(self, file_path):
        url = f"{self.base_url}/files/upload"
        try:
            with open(file_path, "rb") as file:
                response = requests.post(url, headers=self.headers, files={"file": file}, timeout=30)
            return response.json() if response.status_code == 200 else {"error": response.text}
        except Exception as e:
            return {"error": str(e)}
