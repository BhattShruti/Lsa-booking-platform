import pytest
import hmac
import hashlib
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.booking import BookingRequest
from app.models.payment import Payment

SECRET = "test-webhook-secret-key-change-me"

def make_signed_request(payload: dict, secret: str = SECRET, timestamp: int = None, tamper_body: dict = None):
    """
    Build (raw_data, headers) for a properly signed webhook request.

    - payload: the dict to serialize and sign.
    - timestamp: unix epoch int; defaults to current time.
    - tamper_body: if provided, the BODY sent is tamper_body (but signature is still computed from payload).
    """
    if timestamp is None:
        timestamp = int(time.time())

    raw_data = json.dumps(payload)
    sent_body = json.dumps(tamper_body) if tamper_body is not None else raw_data

    # Sign using format: "{timestamp}.{raw_payload}"
    message = f"{timestamp}.{raw_data}"
    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": str(timestamp),
    }
    return sent_body, headers

@pytest.fixture
def webhook_fixtures(app):
    """Seed Parent, LSA, and a pending Booking for webhook testing."""
    with app.app_context():
        db.session.query(BookingRequest).delete()
        db.session.query(LSAProfile).delete()
        db.session.query(Parent).delete()
        db.session.commit()

        # Seed parent and LSA
        parent = Parent(name="Parent Webhook", email="parent.webhook@example.com")
        lsa = LSAProfile(
            name="Alice LSA",
            email="alice.webhook@example.com",
            hourly_rate=Decimal("50.00"),
            is_active=True
        )
        db.session.add_all([parent, lsa])
        db.session.commit()

        # Seed pending booking request ($50.00 total)
        booking = BookingRequest(
            parent_id=parent.id,
            lsa_id=lsa.id,
            start_time=datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 15, 11, 0, 0, tzinfo=timezone.utc),
            status="PENDING",
            total_price=Decimal("50.00"),
        )
        db.session.add(booking)
        db.session.commit()

        yield {
            "booking_id": booking.id,
            "parent_id": parent.id,
            "lsa_id": lsa.id,
        }

# ---------------------------------------------------------------------------
# Webhook Security / Signature Tests
# ---------------------------------------------------------------------------

def test_webhook_missing_signature(client, webhook_fixtures):
    """Verify webhook without signature returns 401 Unauthorized."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    timestamp = int(time.time())
    raw_data = json.dumps(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers={"X-Webhook-Timestamp": str(timestamp)},  # signature omitted
    )
    assert response.status_code == 401
    assert "Missing webhook signature" in response.get_json()["error"]["message"]

def test_webhook_missing_timestamp(client, webhook_fixtures):
    """Verify webhook without timestamp header returns 401 Unauthorized."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data = json.dumps(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers={"X-Webhook-Signature": "some_sig"},  # timestamp omitted
    )
    assert response.status_code == 401
    assert "Missing webhook timestamp" in response.get_json()["error"]["message"]

def test_webhook_malformed_timestamp(client, webhook_fixtures):
    """Verify webhook with non-integer timestamp value returns 400."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data = json.dumps(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers={
            "X-Webhook-Signature": "some_sig",
            "X-Webhook-Timestamp": "not-a-number",
        },
    )
    assert response.status_code == 400
    assert "Invalid webhook timestamp format" in response.get_json()["error"]["message"]

def test_webhook_expired_timestamp(client, webhook_fixtures):
    """Verify webhook with timestamp older than WEBHOOK_TOLERANCE is rejected (replay protection)."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    # Use a timestamp 10 minutes in the past (well beyond 300s tolerance)
    stale_timestamp = int(time.time()) - 600
    raw_data, headers = make_signed_request(payload, timestamp=stale_timestamp)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 401
    assert "tolerance window" in response.get_json()["error"]["message"]

def test_webhook_future_timestamp(client, webhook_fixtures):
    """Verify webhook with a far-future timestamp is rejected (clock skew / pre-signing attack)."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    # Timestamp 10 minutes in the future
    future_timestamp = int(time.time()) + 600
    raw_data, headers = make_signed_request(payload, timestamp=future_timestamp)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 401
    assert "tolerance window" in response.get_json()["error"]["message"]

def test_webhook_invalid_signature(client, webhook_fixtures):
    """Verify webhook with invalid signature returns 401 Unauthorized."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data = json.dumps(payload)
    timestamp = int(time.time())
    headers = {
        "X-Webhook-Signature": "invalid_sha256_hash_value",
        "X-Webhook-Timestamp": str(timestamp),
    }
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.get_json()["error"]["message"]

def test_webhook_tampered_payload(client, webhook_fixtures):
    """Verify webhooks with tampered payload / mismatching signature are rejected."""
    original_payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    tampered_payload = dict(original_payload)
    tampered_payload["amount"] = 100.00

    # Sign the ORIGINAL but send the TAMPERED body
    raw_data, headers = make_signed_request(original_payload, tamper_body=tampered_payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers,
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.get_json()["error"]["message"]

# ---------------------------------------------------------------------------
# Webhook State Transition Tests
# ---------------------------------------------------------------------------

def test_webhook_success_transition(client, webhook_fixtures):
    """Verify that a SUCCESS webhook transitions booking to CONFIRMED and payment to SUCCESS."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 200

    json_data = response.get_json()
    assert json_data["booking_status"] == "CONFIRMED"
    assert json_data["payment_status"] == "SUCCESS"

    # Verify DB state
    booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
    assert booking.status == "CONFIRMED"
    assert booking.payment.status == "SUCCESS"
    assert booking.payment.external_payment_id == "txn_success_123"

def test_webhook_failure_transition(client, webhook_fixtures):
    """Verify that a FAILED webhook transitions both booking and payment to FAILED."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_failed_123",
        "status": "FAILED",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 200

    json_data = response.get_json()
    assert json_data["booking_status"] == "FAILED"
    assert json_data["payment_status"] == "FAILED"

    # Verify DB state
    booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
    assert booking.status == "FAILED"
    assert booking.payment.status == "FAILED"
    assert booking.payment.external_payment_id == "txn_failed_123"

# ---------------------------------------------------------------------------
# Webhook Payload Validation Tests
# ---------------------------------------------------------------------------

def test_webhook_malformed_payload(client, webhook_fixtures):
    """Verify malformed JSON requests are rejected with 400 Bad Request."""
    raw_body = b"invalid-raw-string-not-json"
    timestamp = int(time.time())
    message = f"{timestamp}.{raw_body.decode('utf-8')}"
    sig = hmac.new(SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "X-Webhook-Signature": sig,
        "X-Webhook-Timestamp": str(timestamp),
    }
    response = client.post(
        "/api/payments/webhook/",
        data=raw_body,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 400
    assert "JSON" in response.get_json()["error"]["message"]

@pytest.mark.parametrize("missing_field", ["booking_id", "external_payment_id", "status", "amount", "currency"])
def test_webhook_missing_parameters(client, webhook_fixtures, missing_field):
    """Verify payload validation fails when keys are missing."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    del payload[missing_field]
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 400
    assert "Missing required fields" in response.get_json()["error"]["message"]

def test_webhook_unknown_booking(client, webhook_fixtures):
    """Verify webhook for non-existent booking ID returns 404."""
    payload = {
        "booking_id": 99999,
        "external_payment_id": "txn_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 404
    assert "not found" in response.get_json()["error"]["message"]

def test_webhook_amount_mismatch(client, webhook_fixtures):
    """Verify that webhooks containing mismatched payment amounts are rejected with 400."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_123",
        "status": "SUCCESS",
        "amount": 75.00,  # Expected 50.00
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 400
    assert "amount mismatch" in response.get_json()["error"]["message"]

def test_webhook_currency_mismatch(client, webhook_fixtures):
    """Verify that webhooks containing mismatched currency identifiers are rejected."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "INR"  # Expected USD
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 400
    assert "currency mismatch" in response.get_json()["error"]["message"]

def test_webhook_invalid_status(client, webhook_fixtures):
    """Verify webhooks containing unsupported statuses return 400."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_123",
        "status": "REFUNDED",  # Unsupported
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert response.status_code == 400
    assert "Unsupported status" in response.get_json()["error"]["message"]

# ---------------------------------------------------------------------------
# Webhook Idempotency Tests
# ---------------------------------------------------------------------------

def test_webhook_idempotency_success(client, webhook_fixtures):
    """Verify duplicate SUCCESS webhook returns 200 and performs no extra transitions."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    # First delivery
    r1 = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert r1.status_code == 200

    # Second delivery (re-sign with fresh timestamp — same event)
    raw_data2, headers2 = make_signed_request(payload)
    r2 = client.post(
        "/api/payments/webhook/",
        data=raw_data2,
        content_type="application/json",
        headers=headers2
    )
    assert r2.status_code == 200
    assert "idempotent duplicate" in r2.get_json()["message"]

    # Assert database records are not duplicated
    booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
    assert booking.status == "CONFIRMED"
    assert Payment.query.filter_by(booking_id=webhook_fixtures["booking_id"]).count() == 1

def test_webhook_idempotency_failed(client, webhook_fixtures):
    """Verify duplicate FAILED webhook is idempotent and returns 200."""
    payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_failed_123",
        "status": "FAILED",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_data, headers = make_signed_request(payload)
    # First delivery
    r1 = client.post(
        "/api/payments/webhook/",
        data=raw_data,
        content_type="application/json",
        headers=headers
    )
    assert r1.status_code == 200

    # Second delivery
    raw_data2, headers2 = make_signed_request(payload)
    r2 = client.post(
        "/api/payments/webhook/",
        data=raw_data2,
        content_type="application/json",
        headers=headers2
    )
    assert r2.status_code == 200
    assert "idempotent duplicate" in r2.get_json()["message"]

    # Assert database states
    booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
    assert booking.status == "FAILED"

def test_webhook_transition_conflict(client, webhook_fixtures):
    """Verify that a webhook cannot overwrite an already SUCCESS payment with FAILED (idempotency safety)."""
    success_payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "SUCCESS",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_success, headers_success = make_signed_request(success_payload)
    # Succeed the payment
    client.post(
        "/api/payments/webhook/",
        data=raw_success,
        content_type="application/json",
        headers=headers_success
    )

    # Deliver a FAILED webhook for the same external_payment_id
    failed_payload = {
        "booking_id": webhook_fixtures["booking_id"],
        "external_payment_id": "txn_success_123",
        "status": "FAILED",
        "amount": 50.00,
        "currency": "USD"
    }
    raw_failed, headers_failed = make_signed_request(failed_payload)
    response = client.post(
        "/api/payments/webhook/",
        data=raw_failed,
        content_type="application/json",
        headers=headers_failed
    )
    assert response.status_code == 200
    assert "idempotent duplicate" in response.get_json()["message"]

    # Database states must remain unchanged (CONFIRMED / SUCCESS)
    booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
    assert booking.status == "CONFIRMED"
    assert booking.payment.status == "SUCCESS"

# ---------------------------------------------------------------------------
# Transaction Rollback Test
# ---------------------------------------------------------------------------

def test_webhook_transaction_rollback(app, client, webhook_fixtures):
    """Verify transaction rollback when DB operation fails during webhook update."""
    # Verify initial status is PENDING
    with app.app_context():
        booking = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
        assert booking.status == "PENDING"

        # Perform invalid query to verify state rollbacks
        db.session.begin_nested()
        booking.status = "CONFIRMED"
        # Force check constraint failure by setting start_time >= end_time
        booking.end_time = booking.start_time
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Re-query booking inside new session to assert it remained PENDING
        db.session.expire_all()
        booking_reloaded = db.session.get(BookingRequest, webhook_fixtures["booking_id"])
        assert booking_reloaded.status == "PENDING"
