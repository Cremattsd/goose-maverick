def validate_form_data(data, required_fields):
    errors = []
    for field in required_fields:
        if field not in data or not data[field].strip():
            errors.append(f"Missing or empty field: {field}")
    return errors
