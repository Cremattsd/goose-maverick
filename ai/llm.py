import openai

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
    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}]
    )

    return response["choices"][0]["message"]["content"]
