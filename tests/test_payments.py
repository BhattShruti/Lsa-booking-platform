import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from decimal import Decimal
import requests
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.booking import BookingRequest
from app.models.payment import Payment
from app.services.payment_service import process_booking_payment, PaymentGatewayError

@pytest.fixture
def payment_fixtures(app):
    """Seed data for testing payment gateway services."""
    with app.app_context():
        # Clear existing tables
        db.session.query(BookingRequest).delete()
        db.session.query(LSAProfile).delete()
        db.session.query(Parent).delete()
        db.session.commit()

        # Seed profiles
        parent = Parent(name="Parent Pay", email="parent.pay@example.com")
        parent.set_password("SecurePay123")
        lsa = LSAProfile(
            name="Alice LSA",
            email="alice.pay@example.com",
            hourly_rate=Decimal("50.00"),
            is_active=True
        )
        db.session.add_all([parent, lsa])
        db.session.commit()

        # Create a pending booking
        booking = BookingRequest(
            parent_id=parent.id,
            lsa_id=lsa.id,
            start_time=datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 15, 11, 0, 0, tzinfo=timezone.utc),
            status="PENDING",
            total_price=Decimal("50.00")
        )
        db.session.add(booking)
        db.session.commit()

        yield {
            "booking_id": booking.id,
            "parent_id": parent.id,
            "lsa_id": lsa.id
        }

# Success, POST, URL check, timeout check, response parsing
def test_successful_payment_request(app, client, payment_fixtures, get_auth_headers):
    """Verify that a successful payment response transitions both the payment and booking records appropriately."""
    with app.app_context():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "transaction_id": "tx_mock_12345",
            "status": "SUCCESS"
        }

        # Mock out requests.post call
        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", return_value=mock_response) as mock_post:
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 200

            # Verify outbound call metrics
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == app.config["MOCK_PAYMENT_URL"]
            assert kwargs["json"]["booking_id"] == payment_fixtures["booking_id"]
            assert kwargs["json"]["amount"] == 50.0
            assert kwargs["timeout"] == 5.0

            # Check JSON API response
            json_data = response.get_json()["data"]
            assert json_data["status"] == "SUCCESS"
            assert json_data["external_payment_id"] == "tx_mock_12345"

            # Check database state was updated
            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "CONFIRMED"
            assert booking.payment.status == "SUCCESS"
            assert booking.payment.external_payment_id == "tx_mock_12345"

# External HTTP Error, local state FAILED, app error returned
def test_payment_http_error(app, client, payment_fixtures, get_auth_headers):
    """Verify that HTTP error responses fail the checkout attempt and transition database state to FAILED."""
    with app.app_context():
        mock_response = MagicMock()
        mock_response.status_code = 500

        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", return_value=mock_response):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 502
            
            # Verify central JSON error response
            err = response.get_json()["error"]
            assert err["code"] == "PAYMENT_GATEWAY_ERROR"
            assert "error status" in err["message"]

            # Database states must transition to FAILED to ensure consistency
            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"
            assert booking.payment.status == "FAILED"

# requests.Timeout exception handling
def test_payment_timeout_exception(app, client, payment_fixtures, get_auth_headers):
    """Verify that request timeout exceptions are captured and handled without crashing."""
    with app.app_context():
        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", side_effect=requests.Timeout):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 504
            
            err = response.get_json()["error"]
            assert "timed out" in err["message"]

            # Verify states
            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"
            assert booking.payment.status == "FAILED"

# requests.ConnectionError exception handling
def test_payment_connection_exception(app, client, payment_fixtures, get_auth_headers):
    """Verify that connection failures are caught and return a clean error response."""
    with app.app_context():
        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", side_effect=requests.ConnectionError):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 502
            assert "Could not establish connection" in response.get_json()["error"]["message"]

            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"

# requests.RequestException handling
def test_payment_generic_request_exception(app, client, payment_fixtures, get_auth_headers):
    """Verify that other HTTP library failures are caught and log failures safely."""
    with app.app_context():
        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", side_effect=requests.RequestException("Encountered SSL/protocol error")):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 502
            assert "request failed to execute" in response.get_json()["error"]["message"]

            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"

# Malformed JSON response validation
def test_payment_gateway_invalid_json(app, client, payment_fixtures, get_auth_headers):
    """Verify that unparseable non-JSON payloads are handled and fail the states."""
    with app.app_context():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON data")

        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", return_value=mock_response):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 502
            assert "unparseable response" in response.get_json()["error"]["message"]

            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"

# Missing expected response fields validation
def test_payment_gateway_missing_fields(app, client, payment_fixtures, get_auth_headers):
    """Verify that JSON payloads missing required transaction keys are handled correctly."""
    with app.app_context():
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "error_msg": "Insufficient funds in credit line"
            # Missing status and transaction_id fields
        }

        headers = get_auth_headers(payment_fixtures["parent_id"])
        with patch("app.services.payment_service.requests.post", return_value=mock_response):
            response = client.post(f"/api/v1/bookings/{payment_fixtures['booking_id']}/pay", headers=headers)
            assert response.status_code == 502
            assert "malformed response" in response.get_json()["error"]["message"]

            booking = db.session.get(BookingRequest, payment_fixtures["booking_id"])
            assert booking.status == "FAILED"

# Verification of mock endpoint routes
def test_mock_gateway_endpoint_success(client):
    """Verify mock payment gateway endpoint returns success status for normal amounts."""
    payload = {"booking_id": 1, "amount": 50.00, "currency": "USD"}
    response = client.post("/api/v1/mock-payment-gateway/charge", json=payload)
    assert response.status_code == 200
    assert response.get_json()["status"] == "SUCCESS"
    assert "tx_success_1" in response.get_json()["transaction_id"]

def test_mock_gateway_endpoint_declined(client):
    """Verify mock payment gateway endpoint declines payments for amounts ending in .99."""
    payload = {"booking_id": 1, "amount": 49.99, "currency": "USD"}
    response = client.post("/api/v1/mock-payment-gateway/charge", json=payload)
    assert response.status_code == 200
    assert response.get_json()["status"] == "FAILED"
    assert "declined" in response.get_json()["reason"]
    assert "tx_declined_1" in response.get_json()["transaction_id"]
