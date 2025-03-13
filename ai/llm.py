import openai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def auto_match_fields(extracted_text):
    prompt = f"""
    The following text has been extracted from a file:
    {extracted_text}
    
    Identify and categorize the relevant information:
    - Property Name
    - Address
    - City
    - State
    - Price
    - Cap Rate
    - Number of Units
    - Agent Name
    - Agent Phone
    - Agent Email

    Ensure that all extracted fields align with the RealNex database.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "system", "content": prompt}]
        )

        return response.choices[0].message.content  # Get the text response

    except openai.OpenAIError as e:
        return f"Error with OpenAI API: {str(e)}"
