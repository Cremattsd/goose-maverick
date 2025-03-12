import os

class RealNexAPI:
    def __init__(self):
        self.base_url = "https://sync.realnex.com/api"
        self.api_token = os.getenv("REALNEX_API_TOKEN")

    def authenticate_user(self):
        if not self.api_token:
            return {"error": "No API token found. Please enter your RealNex API token."}

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        response = requests.get(f"{self.base_url}/Client", headers=headers)
        return response.json() if response.status_code == 200 else {"error": "Authentication failed"}

    def store_token(self, new_token):
        os.environ["REALNEX_API_TOKEN"] = new_token
        return {"message": "Token saved successfully!"}
