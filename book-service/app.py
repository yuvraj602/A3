import os

import mysql.connector
from flask import Flask, jsonify, request, Response

from helpers.validation import validate_book
from helpers.llm import fetch_and_store_summary

app = Flask(__name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=os.getenv("DB_NAME", "bookstore"),
    )


@app.get("/status")
def status():
    return Response("OK", status=200, content_type="text/plain")


@app.post("/books")
def add_book():
    try:
        body = request.get_json(silent=True) or {}

        validation_error = validate_book(body)
        if validation_error:
            return jsonify({"message": validation_error}), 400

        isbn = body["ISBN"]
        title = body["title"]
        author = body["Author"]
        description = body["description"]
        genre = body["genre"]
        price = body["price"]
        quantity = body["quantity"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT ISBN FROM books WHERE ISBN = %s", (isbn,))
            existing = cursor.fetchall()
            if existing:
                return jsonify({"message": "This ISBN already exists in the system."}), 422

            cursor.execute(
                "INSERT INTO books (ISBN, title, Author, description, genre, price, quantity) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (isbn, title, author, description, genre, price, quantity),
            )
            conn.commit()

            try:
                fetch_and_store_summary(conn, isbn, title, author)
            except Exception as llm_err:
                print(f"LLM summary error (non-fatal): {llm_err}")

            response_body = {
                "ISBN": isbn,
                "title": title,
                "Author": author,
                "description": description,
                "genre": genre,
                "price": float(price),
                "quantity": quantity,
            }

            base_url = f"{request.scheme}://{request.host}"
            response = jsonify(response_body)
            response.status_code = 201
            response.headers["Location"] = f"{base_url}/books/{isbn}"
            return response
        finally:
            cursor.close()
            conn.close()
    except Exception as err:
        print(f"POST /books error: {err}")
        return jsonify({"message": "Internal server error."}), 500


@app.put("/books/<isbn_param>")
def update_book(isbn_param):
    try:
        body = request.get_json(silent=True) or {}

        validation_error = validate_book(body)
        if validation_error:
            return jsonify({"message": validation_error}), 400

        isbn = body["ISBN"]
        title = body["title"]
        author = body["Author"]
        description = body["description"]
        genre = body["genre"]
        price = body["price"]
        quantity = body["quantity"]

        if isbn != isbn_param:
            return jsonify({"message": "ISBN in URL and payload do not match."}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT ISBN FROM books WHERE ISBN = %s", (isbn_param,))
            existing = cursor.fetchall()
            if not existing:
                return jsonify({"message": "ISBN not found."}), 404

            cursor.execute(
                "UPDATE books SET ISBN = %s, title = %s, Author = %s, description = %s, genre = %s, price = %s, quantity = %s WHERE ISBN = %s",
                (isbn, title, author, description, genre, price, quantity, isbn_param),
            )
            conn.commit()

            response_body = {
                "ISBN": isbn,
                "title": title,
                "Author": author,
                "description": description,
                "genre": genre,
                "price": float(price),
                "quantity": quantity,
            }
            return jsonify(response_body), 200
        finally:
            cursor.close()
            conn.close()
    except Exception as err:
        print(f"PUT /books error: {err}")
        return jsonify({"message": "Internal server error."}), 500


def _get_book_by_isbn(isbn):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM books WHERE ISBN = %s", (isbn,))
        rows = cursor.fetchall()
        if not rows:
            return jsonify({"message": "ISBN not found."}), 404

        book = rows[0]
        response_body = {
            "ISBN": book["ISBN"],
            "title": book["title"],
            "Author": book["Author"],
            "description": book["description"],
            "genre": book["genre"],
            "price": float(book["price"]),
            "quantity": book["quantity"],
            "summary": book.get("summary") or "",
        }
        return jsonify(response_body), 200
    finally:
        cursor.close()
        conn.close()


@app.get("/books/isbn/<isbn>")
def get_book_isbn(isbn):
    try:
        return _get_book_by_isbn(isbn)
    except Exception as err:
        print(f"GET /books/isbn error: {err}")
        return jsonify({"message": "Internal server error."}), 500


@app.get("/books/<isbn>")
def get_book(isbn):
    try:
        return _get_book_by_isbn(isbn)
    except Exception as err:
        print(f"GET /books/:ISBN error: {err}")
        return jsonify({"message": "Internal server error."}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
