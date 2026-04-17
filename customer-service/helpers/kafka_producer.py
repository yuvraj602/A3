"""Thin wrapper around kafka-python's KafkaProducer.

We build a singleton producer lazily and publish fire-and-forget messages to the
`<andrew-id>.customer.evt` topic. Failures are logged but never propagated so
that POST /customers stays independent of Kafka availability.
"""

import json
import os
import threading
from typing import Optional

try:
    from kafka import KafkaProducer  # type: ignore
    from kafka.errors import KafkaError  # type: ignore
except ImportError:  # pragma: no cover - local dev without kafka installed
    KafkaProducer = None  # type: ignore
    KafkaError = Exception  # type: ignore


_producer_lock = threading.Lock()
_producer = None  # type: Optional[object]


def _bootstrap_servers():
    raw = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def _build_kwargs() -> dict:
    kwargs = {
        "bootstrap_servers": _bootstrap_servers(),
        "client_id": os.getenv("KAFKA_CLIENT_ID", "customer-service"),
        "value_serializer": lambda v: json.dumps(v).encode("utf-8"),
        "key_serializer": lambda v: v.encode("utf-8") if isinstance(v, str) else v,
        "acks": "all",
        "retries": int(os.getenv("KAFKA_RETRIES", "3")),
        "request_timeout_ms": int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "10000")),
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


def _get_producer():
    global _producer
    if KafkaProducer is None:
        return None
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is not None:
            return _producer
        servers = _bootstrap_servers()
        if not servers:
            print("KAFKA_BOOTSTRAP_SERVERS not set; Kafka producer disabled.")
            return None
        try:
            _producer = KafkaProducer(**_build_kwargs())
        except KafkaError as exc:
            print(f"Failed to create Kafka producer: {exc}")
            _producer = None
    return _producer


def _topic_name() -> Optional[str]:
    topic = os.getenv("KAFKA_CUSTOMER_TOPIC")
    if topic:
        return topic
    andrew_id = os.getenv("ANDREW_ID")
    if andrew_id:
        return f"{andrew_id}.customer.evt"
    return None


def publish_customer_registered(payload: dict) -> None:
    """Publish a `Customer Registered` domain event. Non-fatal on failure."""

    topic = _topic_name()
    if not topic:
        print("KAFKA_CUSTOMER_TOPIC / ANDREW_ID not set; skipping event publish.")
        return

    producer = _get_producer()
    if producer is None:
        return

    try:
        key = str(payload.get("userId") or payload.get("id") or "")
        future = producer.send(topic, key=key, value=payload)
        future.get(timeout=float(os.getenv("KAFKA_SEND_TIMEOUT_SECONDS", "5")))
        print(f"Published Customer Registered event to topic={topic}")
    except Exception as exc:
        print(f"Kafka publish error (non-fatal): {exc}")
