import openai
import os
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()

# Retrieve API Key from Environment Variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def auto_match_fields(extracted_text, user_fields):
    """
    Dynamically matches extracted text with the user's existing database fields.
    
    :param extracted_text: The text extracted from the uploaded file.
    :param user_fields: A list of all available fields from the user's database.
    :return: JSON object with mapped fields.
    """

    prompt = f"""
    The following text has been extracted from a file:
    {extracted_text}

    The user has the following database fields:
    {json.dumps(user_fields)}

    Match the extracted text with the most relevant fields from the user's database and return the data in JSON format.
    If a field does not match, leave it blank.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "system", "content": prompt}]
        )

        return response.choices[0].message.content  # Return only the text response

    except openai.OpenAIError as e:
        return f"Error with OpenAI API: {str(e)}"

# Example usage
if __name__ == "__main__":
    extracted_text = "Sample text with property details..."
    user_fields = ["Property Name", "Address", "City", "State", "Price", "Cap Rate", "Number of Units", "Agent Name", "Agent Phone", "Agent Email"]
    print(auto_match_fields(extracted_text, user_fields))
