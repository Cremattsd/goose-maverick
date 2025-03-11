import openai
import json
from realnex_api import RealNexAPI  # Import RealNex API SDK to fetch user fields

def fetch_user_fields(api_key):
    """
    Fetch available fields from the user's RealNex database using the API.
    """
    realnex = RealNexAPI(api_key)
    user_fields = realnex.get_fields()  # Hypothetical API call to fetch database fields
    return user_fields if user_fields else ["Unknown Fields"]  # Ensure fallback

def auto_match_fields(api_key, extracted_text):
    """
    Uses OpenAI to match extracted text with user’s actual database fields.
    """
    user_fields = fetch_user_fields(api_key)  # Get real field names from RealNex API

    prompt = f"""
    The following text has been extracted from a file:
    {extracted_text}
    
    Match the extracted information to the most relevant fields from this list:
    {user_fields}
    
    Return the response in JSON format where the keys are the database field names and the values are the matched data.
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an AI assistant that maps extracted data to database fields."},
            {"role": "user", "content": prompt}
        ]
    )

    # Extract AI response
    ai_response = response["choices"][0]["message"]["content"]

    try:
        parsed_data = json.loads(ai_response)  # Convert string to JSON
        return parsed_data
    except json.JSONDecodeError:
        return {"error": "AI response is not valid JSON.", "raw_response": ai_response}
