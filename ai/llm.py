import openai
import json

def auto_match_fields(extracted_text):
    prompt = f"""
    The following text has been extracted from a file:
    {extracted_text}
    
    Identify and categorize the relevant information and return the response in JSON format with the following keys:
    - property_name
    - address
    - city
    - state
    - price
    - cap_rate
    - number_of_units
    - agent_name
    - agent_phone
    - agent_email
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an AI assistant that extracts structured data from text."},
            {"role": "user", "content": prompt}
        ]
    )

    # Extract AI response
    ai_response = response["choices"][0]["message"]["content"]

    try:
        parsed_data = json.loads(ai_response)  # Convert string to JSON if formatted correctly
        return parsed_data
    except json.JSONDecodeError:
        return {"error": "AI response is not in valid JSON format.", "raw_response": ai_response}
