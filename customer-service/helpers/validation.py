import re

VALID_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "AS", "GU", "MP", "PR", "VI", "UM",
}


def validate_customer(body):
    required_fields = ["userId", "name", "phone", "address", "city", "state", "zipcode"]

    for field in required_fields:
        if field not in body or body[field] is None or body[field] == "":
            return f"Missing or empty required field: {field}"

    email_regex = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    if not email_regex.fullmatch(str(body["userId"])):
        return "userId must be a valid email address."

    state = body.get("state")
    if not isinstance(state, str) or state.upper() not in VALID_STATES:
        return "state must be a valid 2-letter US state abbreviation."

    return None
