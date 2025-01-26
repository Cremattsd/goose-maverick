import requests

class RealNexAPI:
    def __init__(self, api_key):
        self.base_url = "https://sync.realnex.com/api/v1"  # Update if needed
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def upload_file(self, file_path):
        """
        Upload a file to the RealNex API.
        """
        url = f"{self.base_url}/files/upload"  # Update endpoint as per Swagger
        with open(file_path, "rb") as file:
            files = {"file": file}
            response = requests.post(url, headers=self.headers, files=files)
        return response.json()

    def fetch_data(self, endpoint, params=None):
        """
        Fetch data from a specific endpoint.
        """
        url = f"{self.base_url}/{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        return response.json()
