import pytest
import threading
import queue
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.booking import BookingRequest
from app.models.payment import Payment

@pytest.fixture
def booking_fixtures(app):
    """Seed data for booking route integration tests."""
    with app.app_context():
        db.session.query(Payment).delete()
        db.session.query(BookingRequest).delete()
        db.session.query(LSAProfile).delete()
        db.session.query(Parent).delete()
        db.session.commit()

        # Seed Parent
        parent = Parent(name="Parent Test", email="parent@example.com")
        parent.set_password("SecureParent123")
        db.session.add(parent)
        db.session.flush()

        # Seed active LSA ($50/hr)
        lsa_active = LSAProfile(
            name="Alice LSA",
            email="alice@example.com",
            hourly_rate=Decimal("50.00"),
            is_active=True
        )
        # Seed inactive LSA ($40/hr)
        lsa_inactive = LSAProfile(
            name="Bob LSA",
            email="bob@example.com",
            hourly_rate=Decimal("40.00"),
            is_active=False
        )
        db.session.add_all([lsa_active, lsa_inactive])
        db.session.commit()

        yield {
            "parent_id": parent.id,
            "lsa_active_id": lsa_active.id,
            "lsa_inactive_id": lsa_inactive.id,
        }

# Success, 201, whole-hour pricing, starts as PENDING
def test_successful_booking_creation(client, booking_fixtures, get_auth_headers):
    """Test successful booking creation with 201 Created and PENDING status."""
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"  # 1.0 hour
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 201
    
    data = response.get_json()["data"]
    assert data["status"] == "PENDING"
    assert data["total_price"] == 50.00  # 1.0 * 50.00
    assert data["parent_id"] == booking_fixtures["parent_id"]
    assert data["lsa_id"] == booking_fixtures["lsa_active_id"]

# Parent does not exist (invalid JWT identity token resolution)
def test_booking_parent_does_not_exist(client, booking_fixtures, get_auth_headers):
    """Test booking fails when parent ID resolved from JWT does not exist in DB."""
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(99999) # valid JWT signature but user doesn't exist
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 401
    assert "not found" in response.get_json()["error"]["message"]

# LSA does not exist
def test_booking_lsa_does_not_exist(client, booking_fixtures, get_auth_headers):
    """Test booking fails when LSA ID does not exist."""
    payload = {
        "lsa_id": 99999,  # invalid
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "LSA_NOT_FOUND"

# Inactive LSA cannot be booked
def test_booking_inactive_lsa(client, booking_fixtures, get_auth_headers):
    """Test booking fails for inactive LSA."""
    payload = {
        "lsa_id": booking_fixtures["lsa_inactive_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "LSA_INACTIVE"

# Missing fields in payload
@pytest.mark.parametrize("missing_field", ["lsa_id", "start_time", "end_time"])
def test_booking_missing_fields(client, booking_fixtures, get_auth_headers, missing_field):
    """Test validation fails for missing keys in request payload."""
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    del payload[missing_field]
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert "Missing required fields" in response.get_json()["error"]["message"]

# Invalid type IDs
def test_booking_invalid_id_types(client, booking_fixtures, get_auth_headers):
    """Test validation fails for non-integer ID fields."""
    payload = {
        "lsa_id": "one",  # string instead of int
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert "lsa_id must be an integer" in response.get_json()["error"]["message"]

# Invalid datetime formatting
def test_booking_invalid_datetime_format(client, booking_fixtures, get_auth_headers):
    """Test validation fails for malformed dates."""
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "invalid-datetime",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert "Invalid ISO-8601 datetime format" in response.get_json()["error"]["message"]

# Logical boundary: start >= end
def test_booking_start_time_after_end_time(client, booking_fixtures, get_auth_headers):
    """Test validation fails if end time is before start time."""
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T12:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 400
    assert "chronologically before" in response.get_json()["error"]["message"]

# Overlaps tests helper
def seed_existing_booking(app, parent_id, lsa_id, start_str, end_str, status="CONFIRMED"):
    """Helper to inject an existing booking directly for overlap testing."""
    with app.app_context():
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        booking = BookingRequest(
            parent_id=parent_id,
            lsa_id=lsa_id,
            start_time=start,
            end_time=end,
            status=status,
            total_price=Decimal("50.00")
        )
        db.session.add(booking)
        db.session.commit()

# Exact overlap
def test_booking_exact_overlap(app, client, booking_fixtures, get_auth_headers):
    """Test exact overlap exclusion."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "BOOKING_CONFLICT"

# Partial overlap at beginning
def test_booking_partial_overlap_beginning(app, client, booking_fixtures, get_auth_headers):
    """Test overlap checking on start times."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T10:30:00Z", "2026-08-15T11:30:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409

# Partial overlap at end
def test_booking_partial_overlap_end(app, client, booking_fixtures, get_auth_headers):
    """Test overlap checking on end times."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T09:30:00Z", "2026-08-15T10:30:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409

# Existing booking completely contains requested interval
def test_booking_existing_contains_requested(app, client, booking_fixtures, get_auth_headers):
    """Test overlap where existing booking surrounds the request window."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T09:00:00Z", "2026-08-15T12:00:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409

# Requested interval completely contains existing booking
def test_booking_requested_contains_existing(app, client, booking_fixtures, get_auth_headers):
    """Test overlap where request window surrounds an existing booking."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T10:15:00Z", "2026-08-15T10:45:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409

# Adjacent booking is allowed
def test_booking_adjacent_allowed(app, client, booking_fixtures, get_auth_headers):
    """Test consecutive/adjacent bookings are allowed."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T09:00:00Z", "2026-08-15T10:00:00Z")
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T11:00:00Z", "2026-08-15T12:00:00Z")
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 201

# CANCELLED/FAILED bookings do not block
@pytest.mark.parametrize("status", ["CANCELLED", "FAILED"])
def test_booking_non_blocking_statuses(app, client, booking_fixtures, get_auth_headers, status):
    """Test non-active status bookings (CANCELLED/FAILED) do not conflict."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z", status=status)
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 201

# PENDING/CONFIRMED bookings block
@pytest.mark.parametrize("status", ["PENDING", "CONFIRMED"])
def test_booking_blocking_statuses(app, client, booking_fixtures, get_auth_headers, status):
    """Test active status bookings (PENDING/CONFIRMED) do conflict."""
    seed_existing_booking(app, booking_fixtures["parent_id"], booking_fixtures["lsa_active_id"], "2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z", status=status)
    
    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-15T10:00:00Z",
        "end_time": "2026-08-15T11:00:00Z"
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 409

# Half-hour and fractional-hour pricing calculations
@pytest.mark.parametrize("duration_mins, expected_price", [
    (30, 25.00),   # 0.5 hours * 50 = 25.00
    (90, 75.00),   # 1.5 hours * 50 = 75.00
    (15, 12.50),   # 0.25 hours * 50 = 12.50
    (45, 37.50),   # 0.75 hours * 50 = 37.50
])
def test_booking_fractional_pricing(client, booking_fixtures, get_auth_headers, duration_mins, expected_price):
    """Test pricing accuracy on fractional hourly calculations."""
    start_dt = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(minutes=duration_mins)

    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }
    headers = get_auth_headers(booking_fixtures["parent_id"])
    response = client.post("/api/v1/bookings/", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.get_json()["data"]["total_price"] == expected_price

# Database rollback behavior when booking creation fails at database level
def test_booking_rollback_on_database_error(app, booking_fixtures):
    """
    Test database rollback safety:
    We attempt to save a booking that triggers database-level CheckConstraint violation
    (end_time before start_time). We verify:
    1. Transaction rolls back and raises IntegrityError.
    2. No invalid rows are persisted in the database.
    """
    with app.app_context():
        invalid_booking = BookingRequest(
            parent_id=booking_fixtures["parent_id"],
            lsa_id=booking_fixtures["lsa_active_id"],
            start_time=datetime.now(timezone.utc) + timedelta(hours=2),
            end_time=datetime.now(timezone.utc) + timedelta(hours=1), # Invalid!
            total_price=Decimal("50.00")
        )
        db.session.add(invalid_booking)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        
        # Verify database is completely empty of bookings
        assert BookingRequest.query.count() == 0

# Concurrency test: Multi-threaded booking execution
def test_concurrent_booking_attempts(app, client, booking_fixtures, get_auth_headers):
    """
    Simulate two concurrent booking requests attempting to allocate the same LSA for the same slot.
    Uses Python threading.
    Expect exactly one thread to return 201 Created and the other to return 409 Conflict.
    
    Note: SQLite ignores 'WITH FOR UPDATE' row-level locks, so this concurrency test
    will only enforce serialization on our canonical database (PostgreSQL). We skip on SQLite.
    """
    with app.app_context():
        if "sqlite" in str(db.engine.url):
            pytest.skip(
                "Pessimistic row-locking (WITH FOR UPDATE) cannot be validated on SQLite. "
                "This verification requires a PostgreSQL or MySQL engine."
            )

    results = queue.Queue()

    payload = {
        "lsa_id": booking_fixtures["lsa_active_id"],
        "start_time": "2026-08-20T14:00:00Z",
        "end_time": "2026-08-20T15:00:00Z"
    }
    
    headers = get_auth_headers(booking_fixtures["parent_id"])

    def post_booking():
        # Running inside threads, creating isolated client requests
        with app.app_context():
            resp = client.post("/api/v1/bookings/", json=payload, headers=headers)
            results.put(resp.status_code)

    # Spawn 2 concurrent request threads
    t1 = threading.Thread(target=post_booking)
    t2 = threading.Thread(target=post_booking)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # Collect outcomes
    outcomes = []
    while not results.empty():
        outcomes.append(results.get())

    # We expect one request to succeed (201) and one to fail with a conflict (409)
    assert 201 in outcomes
    assert 409 in outcomes
    assert len(outcomes) == 2
