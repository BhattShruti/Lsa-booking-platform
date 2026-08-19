import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import event
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.skill import Skill
from app.models.booking import BookingRequest
from app.models.payment import Payment

# QueryCounter to measure database round-trips via SQLAlchemy events
class QueryCounter:
    def __init__(self, engine):
        self.engine = engine
        self.count = 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.callback)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        event.remove(self.engine, "before_cursor_execute", self.callback)

    def callback(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1

@pytest.fixture
def search_fixtures(app):
    """Seed test database with mock records mapping availability overlap boundary scenarios."""
    with app.app_context():
        # Clear database records in dependency order
        db.session.query(Payment).delete()
        db.session.query(BookingRequest).delete()
        db.session.execute(db.metadata.tables["lsa_skills"].delete())
        db.session.query(LSAProfile).delete()
        db.session.query(Parent).delete()
        db.session.query(Skill).delete()
        db.session.commit()

        # Seed 1 Parent
        parent = Parent(name="Parent Test", email="parent.test@example.com")
        db.session.add(parent)
        db.session.flush()

        # Seed Skills
        math = Skill(name="Mathematics")
        english = Skill(name="English")
        db.session.add_all([math, english])
        db.session.flush()

        # Seed LSAs
        # LSA 1: Mathematics, Active, Available
        lsa1 = LSAProfile(name="Alice LSA", email="alice.lsa@example.com", hourly_rate=Decimal("35.00"), is_active=True)
        lsa1.skills.append(math)

        # LSA 2: Mathematics, Active, Overlapping Booking
        lsa2 = LSAProfile(name="Bob LSA", email="bob.lsa@example.com", hourly_rate=Decimal("40.00"), is_active=True)
        lsa2.skills.append(math)

        # LSA 3: Mathematics, Active, Non-overlapping adjacent Bookings
        lsa3 = LSAProfile(name="Charlie LSA", email="charlie.lsa@example.com", hourly_rate=Decimal("30.00"), is_active=True)
        lsa3.skills.append(math)

        # LSA 4: English, Active, Available (Excluded by skill filter)
        lsa4 = LSAProfile(name="Diana LSA", email="diana.lsa@example.com", hourly_rate=Decimal("25.00"), is_active=True)
        lsa4.skills.append(english)

        # LSA 5: Mathematics, Inactive (Excluded by active check)
        lsa5 = LSAProfile(name="Evan LSA", email="evan.lsa@example.com", hourly_rate=Decimal("30.00"), is_active=False)
        lsa5.skills.append(math)

        db.session.add_all([lsa1, lsa2, lsa3, lsa4, lsa5])
        db.session.commit()

        # Set up a canonical test base date: 2026-08-15T10:00:00Z
        base_date = datetime(2026, 8, 15, 10, 0, 0, tzinfo=timezone.utc)

        # Booking for LSA 2: 10:30 to 11:30 (overlaps with requested 10:00 to 11:00)
        booking_overlap = BookingRequest(
            parent_id=parent.id,
            lsa_id=lsa2.id,
            start_time=base_date + timedelta(minutes=30),  # 10:30
            end_time=base_date + timedelta(minutes=90),    # 11:30
            status="CONFIRMED",
            total_price=Decimal("40.00"),
        )

        # Booking for LSA 3: 09:00 to 10:00 (ends exactly at requested start)
        booking_adjacent_start = BookingRequest(
            parent_id=parent.id,
            lsa_id=lsa3.id,
            start_time=base_date - timedelta(hours=1),
            end_time=base_date,
            status="CONFIRMED",
            total_price=Decimal("30.00"),
        )

        # Booking for LSA 3: 11:00 to 12:00 (starts exactly at requested end)
        booking_adjacent_end = BookingRequest(
            parent_id=parent.id,
            lsa_id=lsa3.id,
            start_time=base_date + timedelta(hours=1),
            end_time=base_date + timedelta(hours=2),
            status="CONFIRMED",
            total_price=Decimal("30.00"),
        )

        db.session.add_all([booking_overlap, booking_adjacent_start, booking_adjacent_end])
        db.session.commit()

        yield {
            "base_date": base_date,
            "parent_id": parent.id,
            "math_skill": math,
        }

# ---------------------------------------------------------------------------
# 1-6. Integration tests on search filters
# ---------------------------------------------------------------------------

def test_successful_skill_availability_search(client, search_fixtures):
    """Test standard valid search returning available LSAs only, filtering skills, overlap, and status."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    
    response = client.get(f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}")
    assert response.status_code == 200
    
    json_data = response.get_json()
    assert "data" in json_data
    assert "pagination" in json_data
    
    # Expected: Alice LSA (LSA 1) and Charlie LSA (LSA 3)
    # Excluded: Bob (LSA 2 - overlap), Diana (LSA 4 - wrong skill), Evan (LSA 5 - inactive)
    data = json_data["data"]
    assert len(data) == 2
    
    names = [item["name"] for item in data]
    assert "Alice LSA" in names
    assert "Charlie LSA" in names
    assert "Bob LSA" not in names
    assert "Diana LSA" not in names
    assert "Evan LSA" not in names

    # Validate pagination metadata
    pagination = json_data["pagination"]
    assert pagination["total"] == 2
    assert pagination["page"] == 1
    assert pagination["per_page"] == 10
    assert pagination["pages"] == 1
    assert pagination["has_next"] is False
    assert pagination["has_prev"] is False

# 7. Search returning empty data
def test_search_returning_no_results(client, search_fixtures):
    """Test query returning zero matched LSAs when the skill does not exist or matches nothing."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    
    response = client.get(f"/api/v1/lsas/search?skill=Geography&start_time={start_str}&end_time={end_str}")
    assert response.status_code == 200
    
    json_data = response.get_json()
    assert json_data["data"] == []
    pagination = json_data["pagination"]
    assert pagination["total"] == 0
    assert pagination["pages"] == 0
    assert pagination["has_next"] is False
    assert pagination["has_prev"] is False

# 8. Missing skill parameter
def test_search_missing_skill(client, search_fixtures):
    """Test validator catches missing skill."""
    start_str = "2026-08-15T10:00:00Z"
    response = client.get(f"/api/v1/lsas/search?start_time={start_str}&end_time=2026-08-15T11:00:00Z")
    assert response.status_code == 400
    assert "skill" in response.get_json()["error"]["message"]

# 9. Missing start_time
def test_search_missing_start_time(client, search_fixtures):
    """Test validator catches missing start_time."""
    response = client.get("/api/v1/lsas/search?skill=Mathematics&end_time=2026-08-15T11:00:00Z")
    assert response.status_code == 400
    assert "start_time" in response.get_json()["error"]["message"]

# 10. Missing end_time
def test_search_missing_end_time(client, search_fixtures):
    """Test validator catches missing end_time."""
    response = client.get("/api/v1/lsas/search?skill=Mathematics&start_time=2026-08-15T10:00:00Z")
    assert response.status_code == 400
    assert "end_time" in response.get_json()["error"]["message"]

# 11. Invalid datetime formats
def test_search_invalid_datetime_format(client, search_fixtures):
    """Test validator catches malformed ISO-8601 strings."""
    response = client.get("/api/v1/lsas/search?skill=Mathematics&start_time=invalid-date&end_time=2026-08-15T11:00:00Z")
    assert response.status_code == 400
    assert "invalid-date" in response.get_json()["error"]["message"]

# 12. Logical date boundaries: start_time >= end_time
def test_search_start_time_after_end_time(client, search_fixtures):
    """Test validator catches chronological errors."""
    start_str = "2026-08-15T12:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}")
    assert response.status_code == 400
    assert "chronologically before" in response.get_json()["error"]["message"]

# 13. Case insensitive skill search
def test_case_insensitive_skill_search(client, search_fixtures):
    """Test query matching normalized case names (e.g. 'mAtHeMaTiCs' matches 'Mathematics')."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(f"/api/v1/lsas/search?skill=mAtHeMaTiCs&start_time={start_str}&end_time={end_str}")
    assert response.status_code == 200
    json_data = response.get_json()
    assert len(json_data["data"]) == 2
    assert json_data["pagination"]["total"] == 2

# ---------------------------------------------------------------------------
# Pagination-specific tests
# ---------------------------------------------------------------------------

def test_search_pagination_first_page(app, client, search_fixtures):
    """Test that per_page=1 returns only one result and correct pagination metadata."""
    # Add a third available math LSA to have 3 total results
    with app.app_context():
        math_skill = Skill.query.filter_by(name="Mathematics").first()
        extra = LSAProfile(name="Extra LSA", email="extra@example.com", hourly_rate=Decimal("20.00"), is_active=True)
        extra.skills.append(math_skill)
        db.session.add(extra)
        db.session.commit()

    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&page=1&per_page=1"
    )
    assert response.status_code == 200
    json_data = response.get_json()
    assert len(json_data["data"]) == 1
    pagination = json_data["pagination"]
    assert pagination["page"] == 1
    assert pagination["per_page"] == 1
    assert pagination["total"] == 3
    assert pagination["pages"] == 3
    assert pagination["has_next"] is True
    assert pagination["has_prev"] is False

def test_search_pagination_second_page(app, client, search_fixtures):
    """Test that page=2 per_page=1 returns the second result."""
    with app.app_context():
        math_skill = Skill.query.filter_by(name="Mathematics").first()
        extra = LSAProfile(name="Extra LSA", email="extra@example.com", hourly_rate=Decimal("20.00"), is_active=True)
        extra.skills.append(math_skill)
        db.session.add(extra)
        db.session.commit()

    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&page=2&per_page=1"
    )
    assert response.status_code == 200
    json_data = response.get_json()
    assert len(json_data["data"]) == 1
    pagination = json_data["pagination"]
    assert pagination["page"] == 2
    assert pagination["has_next"] is True
    assert pagination["has_prev"] is True

def test_search_pagination_beyond_last_page(client, search_fixtures):
    """Test that requesting a page beyond the last page returns empty data."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&page=100&per_page=10"
    )
    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["data"] == []
    assert json_data["pagination"]["total"] == 2  # 2 available LSAs seeded

def test_search_pagination_invalid_page(client, search_fixtures):
    """Test validation catches invalid page values."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&page=0"
    )
    assert response.status_code == 400
    assert "page" in response.get_json()["error"]["message"]

def test_search_pagination_per_page_exceeds_max(client, search_fixtures):
    """Test validation catches per_page values exceeding the maximum."""
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&per_page=999"
    )
    assert response.status_code == 400
    assert "per_page" in response.get_json()["error"]["message"]

def test_search_stable_ordering(app, client, search_fixtures):
    """Test that results are returned in stable ascending ID order across pages."""
    with app.app_context():
        math_skill = Skill.query.filter_by(name="Mathematics").first()
        for i in range(3):
            extra = LSAProfile(
                name=f"ZExtra LSA {i}",
                email=f"zextra{i}@example.com",
                hourly_rate=Decimal("20.00"),
                is_active=True
            )
            extra.skills.append(math_skill)
            db.session.add(extra)
        db.session.commit()

    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"
    # Fetch all in one page
    response = client.get(
        f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}&per_page=50"
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.get_json()["data"]]
    # IDs must be in ascending order
    assert ids == sorted(ids)

# ---------------------------------------------------------------------------
# 14. N+1 behavior validation
# ---------------------------------------------------------------------------

def test_search_prevents_n_plus_one_queries(app, client, search_fixtures):
    """
    Test proving that the SQL query count remains bounded rather than scaling
    with the number of matching database records.
    
    Steps:
    1. Measure query count for 2 matching LSAs.
    2. Add 5 more matching LSAs (total 7).
    3. Measure query count again.
    4. Assert that query counts remain identical (bounded).
    """
    start_str = "2026-08-15T10:00:00Z"
    end_str = "2026-08-15T11:00:00Z"

    # Step 1: Measure with original seeded data (2 matching LSAs: Alice, Charlie)
    with app.app_context():
        with QueryCounter(db.engine) as counter_initial:
            response = client.get(f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}")
            assert response.status_code == 200
            assert len(response.get_json()["data"]) == 2
        queries_with_2_lsas = counter_initial.count

    # Step 2: Inject 5 additional available LSAs matching the criteria
    with app.app_context():
        math_skill = Skill.query.filter_by(name="Mathematics").first()
        for i in range(5):
            extra_lsa = LSAProfile(
                name=f"Extra LSA {i}",
                email=f"extra.lsa.{i}@example.com",
                hourly_rate=Decimal("30.00"),
                is_active=True
            )
            extra_lsa.skills.append(math_skill)
            db.session.add(extra_lsa)
        db.session.commit()

    # Step 3: Measure with updated records (7 matching LSAs: Alice, Charlie + 5 extras)
    with app.app_context():
        with QueryCounter(db.engine) as counter_final:
            response = client.get(f"/api/v1/lsas/search?skill=Mathematics&start_time={start_str}&end_time={end_str}")
            assert response.status_code == 200
            assert len(response.get_json()["data"]) == 7
        queries_with_7_lsas = counter_final.count

    # Step 4: Validate query bound is identical.
    # N+1 would cause count to grow with more records.
    assert queries_with_2_lsas == queries_with_7_lsas
