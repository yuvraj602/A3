import base64
import json
import time

VALID_SUBS = {"starlord", "gamora", "drax", "rocket", "groot"}


def validate_jwt(auth_header):
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    parts = token.split(".")
    if len(parts) != 3:
        return None

    try:
        payload = parts[1].replace("-", "+").replace("_", "/")
        while len(payload) % 4 != 0:
            payload += "="
        decoded = json.loads(base64.b64decode(payload).decode("utf-8"))

        if not decoded.get("sub") or decoded["sub"] not in VALID_SUBS:
            return None

        if not decoded.get("exp") or not isinstance(decoded["exp"], (int, float)) or decoded["exp"] <= int(time.time()):
            return None

        if not decoded.get("iss") or decoded["iss"] != "cmu.edu":
            return None

        return decoded
    except Exception:
        return None
