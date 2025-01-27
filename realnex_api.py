import requests
import logging

logger = logging.getLogger(__name__)

class RealNexAPI:
    def __init__(self, api_key):
        self.base_url = "https://sync.realnex.com/api"  # Base URL for the API
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def authenticate(self):
        """
        Authenticate the user using the /api/Client endpoint.
        """
        url = f"{self.base_url}/Client"
        try:
            response = requests.get(url, headers=self.headers, timeout=10)  # Added timeout
            logger.info(f"Authentication Response Status Code: {response.status_code}")
            logger.info(f"Authentication Response Content: {response.text}")

            if response.status_code == 200:
                return response.json()  # Return the response data
            else:
                error_message = response.json().get("message", response.text)
                logger.error(f"Authentication failed: {error_message}")
                return {"error": error_message}
        except requests.exceptions.Timeout:
            logger.error("Authentication request timed out")
            return {"error": "Request timed out"}
        except Exception as e:
            logger.error(f"Error during authentication: {str(e)}")
            return {"error": str(e)}

    def upload_file(self, file_path):
        """
        Upload a file to the RealNex API.
        """
        url = f"{self.base_url}/Client/upload"  # Adjust endpoint as needed
        try:
            with open(file_path, "rb") as file:
                files = {"file": file}
                response = requests.post(url, headers=self.headers, files=files, timeout=30)  # Added timeout
            
            logger.info(f"Upload Response Status Code: {response.status_code}")
            logger.info(f"Upload Response Content: {response.text}")

            if response.status_code == 200:
                return response.json()  # Return the response data
            else:
                error_message = response.json().get("message", response.text)
                logger.error(f"Upload failed: {error_message}")
                return {"error": error_message}
        except requests.exceptions.Timeout:
            logger.error("File upload request timed out")
            return {"error": "Request timed out"}
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return {"error": str(e)}
