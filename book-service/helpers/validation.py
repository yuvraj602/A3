import re
from decimal import Decimal, InvalidOperation


def validate_book(body):
    required_fields = ["ISBN", "title", "Author", "description", "genre", "price", "quantity"]

    for field in required_fields:
        if field not in body or body[field] is None or body[field] == "":
            return f"Missing or empty required field: {field}"

    price = body.get("price")
    if isinstance(price, bool):
        return "Invalid price value."

    if isinstance(price, (int, float)):
        try:
            d = Decimal(str(price))
        except InvalidOperation:
            return "Invalid price value."
        if d < 0:
            return "Price must not be negative."
        if abs(d.as_tuple().exponent) > 2:
            return "Price must have 0-2 decimal places."
    elif isinstance(price, str):
        if not re.fullmatch(r"^\d+(\.\d{1,2})?$", price):
            return "Price must be a valid number with 0-2 decimal places."
    else:
        return "Invalid price value."

    return None
