import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.booking import BookingRequest
from app.models.payment import Payment

@pytest.fixture
def security_fixtures(app):
    """Seed data for security and authorization boundary testing."""
    with app.app_context():
        # Clear tables
        db.session.query(Payment).delete()
        db.session.query(BookingRequest).delete()
        db.session.query(LSAProfile).delete()
        db.session.query(Parent).delete()
        db.session.commit()

        # Seed two parents (User A and User B)
        parent_a = Parent(name="User A", email="usera@example.com")
        parent_a.set_password("PasswordA123")
        parent_b = Parent(name="User B", email="userb@example.com")
        parent_b.set_password("PasswordB123")
        db.session.add_all([parent_a, parent_b])
        db.session.flush()

        # Seed LSA
        lsa = LSAProfile(
            name="Alice LSA",
            email="alice@example.com",
            hourly_rate=Decimal("50.00"),
            is_active=True
        )
        db.session.add(lsa)
        db.session.commit()

        # Seed a booking for User B
        booking_b = BookingRequest(
            parent_id=parent_b.id,
            lsa_id=lsa.id,
            start_time=datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 15, 11, 0, 0, tzinfo=timezone.utc),
            status="PENDING",
            total_price=Decimal("50.00")
        )
        db.session.add(booking_b)
        db.session.commit()

        yield {
            "parent_a_id": parent_a.id,
            "parent_b_id": parent_b.id,
            "lsa_id": lsa.id,
            "booking_b_id": booking_b.id
        }

# --- Registration / Login Security Tests ---

def test_duplicate_email_registration_case_insensitive(client, security_fixtures):
    """Verify registration fails for existing email (case variation)."""
    # Original is userb@example.com
    payload = {
        "name": "New User",
        "email": "USERB@example.com",
        "password": "PasswordNew123"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "already exists" in response.get_json()["error"]["message"]

def test_password_hash_not_plaintext_and_never_returned(client, security_fixtures):
    """Verify password hash is not plaintext and never returned in responses."""
    # 1. Check register response does not contain password hash
    payload = {
        "name": "Register Test",
        "email": "registertest@example.com",
        "password": "SecretPassword123"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    reg_data = response.get_json()["data"]
    assert "password" not in reg_data
    assert "password_hash" not in reg_data

    # Verify db hash is not plaintext
    parent = Parent.query.filter_by(email="registertest@example.com").first()
    assert parent.password_hash is not None
    assert "SecretPassword123" not in parent.password_hash

    # 2. Check login response does not contain password hash
    login_payload = {
        "email": "registertest@example.com",
        "password": "SecretPassword123"
    }
    login_response = client.post("/api/v1/auth/login", json=login_payload)
    assert login_response.status_code == 200
    assert "access_token" in login_response.get_json()
    assert "password" not in login_response.get_json()
    assert "password_hash" not in login_response.get_json()

    # 3. Check /me response does not contain password hash
    token = login_response.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 200
    me_data = me_response.get_json()["data"]
    assert "password" not in me_data
    assert "password_hash" not in me_data

# --- Token Validation Tests ---

def test_missing_jwt(client, security_fixtures):
    """Verify protected endpoints reject requests with missing JWT."""
    # Booking creation
    payload = {
        "lsa_id": security_fixtures["lsa_id"],
        "start_time": "2026-08-15T12:00:00Z",
        "end_time": "2026-08-15T13:00:00Z"
    }
    r1 = client.post("/api/v1/bookings/", json=payload)
    assert r1.status_code == 401

    # Payment
    r2 = client.post(f"/api/v1/bookings/{security_fixtures['booking_b_id']}/pay")
    assert r2.status_code == 401

def test_malformed_jwt(client, security_fixtures):
    """Verify protected endpoints reject requests with malformed JWT."""
    headers = {"Authorization": "Bearer malformed_token_value_here"}
    r1 = client.post("/api/v1/bookings/", json={}, headers=headers)
    assert r1.status_code == 422  # Flask-JWT-Extended returns 422 for malformed tokens

def test_expired_jwt(app, client, security_fixtures):
    """Verify protected endpoints reject expired JWTs."""
    with app.app_context():
        # Create token with past expiration
        token = create_access_token(
            identity=str(security_fixtures["parent_a_id"]),
            expires_delta=timedelta(seconds=-10)
        )
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "lsa_id": security_fixtures["lsa_id"],
        "start_time": "2026-08-15T12:00:00Z",
        "end_time": "2026-08-15T13:00:00Z"
    }
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 401
    assert "expired" in response.get_json()["msg"].lower()

# --- Authorization & Impersonation Tests ---

def test_user_a_accessing_user_b_booking(client, security_fixtures, get_auth_headers):
    """Verify User A cannot pay for User B's booking (403 Forbidden)."""
    headers = get_auth_headers(security_fixtures["parent_a_id"])
    
    # Try to pay for User B's booking
    response = client.post(f"/api/v1/bookings/{security_fixtures['booking_b_id']}/pay", headers=headers)
    assert response.status_code == 403
    assert "denied" in response.get_json()["error"]["message"].lower()

def test_parent_id_impersonation_attempt(client, security_fixtures, get_auth_headers):
    """Verify client cannot specify parent_id in booking creation (400 Bad Request)."""
    headers = get_auth_headers(security_fixtures["parent_a_id"])
    payload = {
        "parent_id": security_fixtures["parent_b_id"], # attempt to impersonate User B
        "lsa_id": security_fixtures["lsa_id"],
        "start_time": "2026-08-15T12:00:00Z",
        "end_time": "2026-08-15T13:00:00Z"
    }
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert "parent_id is not allowed" in response.get_json()["error"]["message"]
