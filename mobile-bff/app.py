import os

import requests
from flask import Flask, Response, jsonify, request

from helpers.jwt import validate_jwt

app = Flask(__name__)

BACKEND_URL = os.getenv("URL_BASE_BACKEND_SERVICES", "http://localhost:3000")


@app.get("/status")
def status():
    return Response("OK", status=200, content_type="text/plain")


@app.before_request
def auth_middleware():
    if request.path == "/status":
        return None
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"message": "Authorization header is missing."}), 401
    decoded = validate_jwt(auth_header)
    if not decoded:
        return jsonify({"message": "Invalid or expired JWT token."}), 401
    return None


def transform_book_genre(body):
    if isinstance(body, dict) and body.get("genre") == "non-fiction":
        body["genre"] = 3
    return body


def transform_customer_for_mobile(body):
    if isinstance(body, dict):
        body.pop("address", None)
        body.pop("address2", None)
        body.pop("city", None)
        body.pop("state", None)
        body.pop("zipcode", None)
    return body


def proxy_to_backend(transform_fn=None):
    path = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    url = f"{BACKEND_URL.rstrip('/')}{path}"

    headers = {"Content-Type": "application/json"}
    data = None
    body = request.get_json(silent=True)
    if body and isinstance(body, dict) and len(body.keys()) > 0:
        data = request.get_data()

    try:
        proxy_res = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=data,
            timeout=60,
            allow_redirects=False,
        )
    except requests.Timeout:
        return jsonify({"message": "Backend service timeout."}), 504
    except requests.RequestException as exc:
        print(f"Proxy error: {exc}")
        return jsonify({"message": "Backend service unavailable."}), 502

    if transform_fn and 200 <= proxy_res.status_code < 300:
        try:
            parsed = proxy_res.json()
            transformed = transform_fn(parsed)
            out = jsonify(transformed)
            out.status_code = proxy_res.status_code
            if proxy_res.headers.get("Location"):
                out.headers["Location"] = proxy_res.headers["Location"]
            return out
        except ValueError:
            pass

    out = Response(
        proxy_res.content,
        status=proxy_res.status_code,
        content_type=proxy_res.headers.get("Content-Type", "application/json"),
    )
    if proxy_res.headers.get("Location"):
        out.headers["Location"] = proxy_res.headers["Location"]
    return out


@app.route("/books/isbn/<isbn>", methods=["GET"])
def books_isbn(isbn):
    return proxy_to_backend(transform_book_genre)


@app.route("/books/<isbn>", methods=["GET"])
def books_detail(isbn):
    return proxy_to_backend(transform_book_genre)


@app.route("/books", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@app.route("/books/<path:path_suffix>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def books_all(path_suffix=None):
    return proxy_to_backend(None)


@app.route("/customers/<id_value>", methods=["GET"])
def customers_detail(id_value):
    return proxy_to_backend(transform_customer_for_mobile)


@app.route("/customers", methods=["GET"])
def customers_get():
    if request.args.get("userId"):
        return proxy_to_backend(transform_customer_for_mobile)
    return proxy_to_backend(None)


@app.route("/customers", methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
@app.route("/customers/<path:path_suffix>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def customers_all(path_suffix=None):
    return proxy_to_backend(None)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "80"))
    app.run(host="0.0.0.0", port=port)
