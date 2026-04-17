import os
import re
import time

import mysql.connector
from flask import Flask, jsonify, request, Response

from helpers.validation import validate_customer
from helpers.kafka_producer import publish_customer_registered

app = Flask(__name__)


def _db_config():
    host = os.getenv("MYSQL_HOST") or os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT") or os.getenv("DB_PORT", "3306"))
    user = os.getenv("MYSQL_USER") or os.getenv("DB_USER", "root")
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASS", "")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("DB_NAME", "customers")
    return host, port, user, password, database


def initialize_schema():
    db_host, db_port, db_user, db_pass, db_name = _db_config()

    retries = int(os.getenv("DB_INIT_RETRIES", "30"))
    delay_seconds = float(os.getenv("DB_INIT_DELAY_SECONDS", "2"))
    last_error = None

    for attempt in range(1, retries + 1):
        conn = None
        cursor = None
        try:
            conn = mysql.connector.connect(
                host=db_host,
                port=db_port,
                user=db_user,
                password=db_pass,
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
            cursor.execute(f"USE `{db_name}`")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    userId VARCHAR(255) NOT NULL UNIQUE,
                    name VARCHAR(255) NOT NULL,
                    phone VARCHAR(50) NOT NULL,
                    address VARCHAR(255) NOT NULL,
                    address2 VARCHAR(255) NOT NULL DEFAULT '',
                    city VARCHAR(100) NOT NULL,
                    state VARCHAR(2) NOT NULL,
                    zipcode VARCHAR(20) NOT NULL
                )
                """
            )
            conn.commit()
            print("Database schema ensured for customer-service.")
            return
        except Exception as err:
            last_error = err
            print(f"Schema init attempt {attempt}/{retries} failed: {err}")
            time.sleep(delay_seconds)
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    raise RuntimeError(f"Unable to initialize schema for customer-service: {last_error}")


def get_db_connection():
    db_host, db_port, db_user, db_pass, db_name = _db_config()
    return mysql.connector.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_pass,
        database=db_name,
    )


@app.get("/status")
def status():
    return Response("OK", status=200, content_type="text/plain")


@app.get("/customers")
def get_customer_query():
    try:
        user_id = request.args.get("userId")
        if not user_id:
            return jsonify({"message": "Missing userId query parameter."}), 400

        email_regex = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        if not email_regex.fullmatch(user_id):
            return jsonify({"message": "Invalid email format."}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM customers WHERE userId = %s", (user_id,))
            rows = cursor.fetchall()
            if not rows:
                return jsonify({"message": "User-ID not found."}), 404

            customer = rows[0]
            response_body = {
                "id": customer["id"],
                "userId": customer["userId"],
                "name": customer["name"],
                "phone": customer["phone"],
                "address": customer["address"],
                "address2": customer.get("address2") or "",
                "city": customer["city"],
                "state": customer["state"],
                "zipcode": customer["zipcode"],
            }
            return jsonify(response_body), 200
        finally:
            cursor.close()
            conn.close()
    except Exception as err:
        print(f"GET /customers?userId error: {err}")
        return jsonify({"message": "Internal server error."}), 500


@app.post("/customers")
def add_customer():
    try:
        body = request.get_json(silent=True) or {}

        validation_error = validate_customer(body)
        if validation_error:
            return jsonify({"message": validation_error}), 400

        user_id = body["userId"]
        name = body["name"]
        phone = body["phone"]
        address = body["address"]
        city = body["city"]
        state = body["state"]
        zipcode = body["zipcode"]
        address2 = body.get("address2") or ""

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id FROM customers WHERE userId = %s", (user_id,))
            existing = cursor.fetchall()
            if existing:
                return jsonify({"message": "This user ID already exists in the system."}), 422

            cursor.execute(
                "INSERT INTO customers (userId, name, phone, address, address2, city, state, zipcode) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, name, phone, address, address2, city, state, zipcode),
            )
            conn.commit()
            new_id = cursor.lastrowid

            response_body = {
                "id": new_id,
                "userId": user_id,
                "name": name,
                "phone": phone,
                "address": address,
                "address2": address2,
                "city": city,
                "state": state,
                "zipcode": zipcode,
            }

            try:
                publish_customer_registered(response_body)
            except Exception as kafka_err:
                print(f"Kafka publish failed (non-fatal): {kafka_err}")

            base_url = f"{request.scheme}://{request.host}"
            response = jsonify(response_body)
            response.status_code = 201
            response.headers["Location"] = f"{base_url}/customers/{new_id}"
            return response
        finally:
            cursor.close()
            conn.close()
    except Exception as err:
        print(f"POST /customers error: {err}")
        return jsonify({"message": "Internal server error."}), 500


@app.get("/customers/<id_value>")
def get_customer_by_id(id_value):
    try:
        if not id_value.isdigit() or int(id_value) < 1:
            return jsonify({"message": "Invalid customer ID."}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM customers WHERE id = %s", (int(id_value),))
            rows = cursor.fetchall()
            if not rows:
                return jsonify({"message": "Customer not found."}), 404

            customer = rows[0]
            response_body = {
                "id": customer["id"],
                "userId": customer["userId"],
                "name": customer["name"],
                "phone": customer["phone"],
                "address": customer["address"],
                "address2": customer.get("address2") or "",
                "city": customer["city"],
                "state": customer["state"],
                "zipcode": customer["zipcode"],
            }
            return jsonify(response_body), 200
        finally:
            cursor.close()
            conn.close()
    except Exception as err:
        print(f"GET /customers/:id error: {err}")
        return jsonify({"message": "Internal server error."}), 500


if __name__ == "__main__":
    initialize_schema()
    port = int(os.getenv("PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
