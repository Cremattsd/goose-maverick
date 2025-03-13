import requests
import os

class RealNexAPI:
    def __init__(self, token):
        self.base_url = "https://sync.realnex.com/api"
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_user_data(self):
        url = f"{self.base_url}/Client"
        response = requests.get(url, headers=self.headers)
        return response.json() if response.status_code == 200 else {"error": response.text}
