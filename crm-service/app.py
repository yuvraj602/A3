"""CRM asynchronous service.

Subscribes to `<ANDREW_ID>.customer.evt` on Kafka. For every message the service
parses the JSON payload and sends a welcome email via SMTP to the newly
registered customer's email address (the `userId` field).
"""

import json
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage

from kafka import KafkaConsumer
from kafka.errors import KafkaError, NoBrokersAvailable


def _bootstrap_servers():
    raw = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _topic_name():
    topic = os.getenv("KAFKA_CUSTOMER_TOPIC")
    if topic:
        return topic
    andrew_id = os.getenv("ANDREW_ID")
    if andrew_id:
        return f"{andrew_id}.customer.evt"
    return None


def _build_consumer_kwargs():
    kwargs = {
        "bootstrap_servers": _bootstrap_servers(),
        "client_id": os.getenv("KAFKA_CLIENT_ID", "crm-service"),
        "group_id": os.getenv("KAFKA_GROUP_ID", "crm-service"),
        "auto_offset_reset": os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
        "enable_auto_commit": True,
        "value_deserializer": lambda b: json.loads(b.decode("utf-8")),
        "key_deserializer": lambda b: b.decode("utf-8") if b is not None else None,
        "consumer_timeout_ms": 0,
    }

    security = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT").upper()
    kwargs["security_protocol"] = security

    if security in ("SASL_PLAINTEXT", "SASL_SSL"):
        kwargs["sasl_mechanism"] = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")
        kwargs["sasl_plain_username"] = os.getenv("KAFKA_SASL_USERNAME")
        kwargs["sasl_plain_password"] = os.getenv("KAFKA_SASL_PASSWORD")

    if security in ("SSL", "SASL_SSL") and os.getenv("KAFKA_SSL_CAFILE"):
        kwargs["ssl_cafile"] = os.getenv("KAFKA_SSL_CAFILE")

    return kwargs


def _create_consumer(topic, retries=30, delay=5):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return KafkaConsumer(topic, **_build_consumer_kwargs())
        except NoBrokersAvailable as err:
            last_err = err
            print(f"Kafka not reachable (attempt {attempt}/{retries}): {err}")
        except KafkaError as err:
            last_err = err
            print(f"Kafka consumer error (attempt {attempt}/{retries}): {err}")
        time.sleep(delay)
    raise RuntimeError(f"Unable to create Kafka consumer: {last_err}")


def _build_email(customer):
    andrew_id = os.getenv("ANDREW_ID", "the-andrew-id")
    name = customer.get("name") or "Customer"
    to_addr = customer.get("userId")

    msg = EmailMessage()
    msg["Subject"] = "Activate your book store account"
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME", "")
    msg["To"] = to_addr

    body = (
        f"Dear {name},\n\n"
        f"Welcome to the Book store created by {andrew_id}.\n"
        "Exceptionally this time we won't ask you to click a link to activate your account.\n"
    )
    msg.set_content(body)
    return msg


def _send_email(msg):
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes")
    use_starttls = os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")
    timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))

    context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as smtp:
            if username:
                smtp.login(username, password or "")
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        if use_starttls:
            smtp.starttls(context=context)
            smtp.ehlo()
        if username:
            smtp.login(username, password or "")
        smtp.send_message(msg)


def _handle_event(event):
    if not isinstance(event, dict):
        print(f"Skipping non-dict event: {event!r}")
        return

    to_addr = event.get("userId")
    if not to_addr:
        print(f"Event missing userId, skipping: {event}")
        return

    try:
        msg = _build_email(event)
        _send_email(msg)
        print(f"Welcome email sent to {to_addr}")
    except Exception as exc:
        print(f"Failed to send welcome email to {to_addr}: {exc}")


def main():
    topic = _topic_name()
    if not topic:
        print("Neither KAFKA_CUSTOMER_TOPIC nor ANDREW_ID is set; exiting.")
        sys.exit(1)

    servers = _bootstrap_servers()
    if not servers:
        print("KAFKA_BOOTSTRAP_SERVERS not set; exiting.")
        sys.exit(1)

    print(f"CRM service starting. Subscribing to topic={topic} on {servers}")
    consumer = _create_consumer(topic)

    try:
        for message in consumer:
            print(f"Received event on {message.topic} partition={message.partition} offset={message.offset}")
            _handle_event(message.value)
    except KeyboardInterrupt:
        print("Stopping CRM service ...")
    finally:
        try:
            consumer.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
