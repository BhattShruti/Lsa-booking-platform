import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.skill import Skill
from app.models.booking import BookingRequest
from app.models.payment import Payment

def test_parent_creation(app):
    """Verify Parent properties, default values, and successful persistence."""
    parent = Parent(name="Alice Parent", email="alice.parent@example.com")
    db.session.add(parent)
    db.session.commit()

    assert parent.id is not None
    assert parent.name == "Alice Parent"
    assert parent.email == "alice.parent@example.com"
    assert parent.created_at is not None
    assert parent.updated_at is not None

def test_parent_email_uniqueness(app):
    """Verify that multiple Parent profiles cannot share the same email."""
    parent1 = Parent(name="Alice Parent", email="duplicate@example.com")
    db.session.add(parent1)
    db.session.commit()

    parent2 = Parent(name="Bob Parent", email="duplicate@example.com")
    db.session.add(parent2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_lsa_creation_and_skills(app):
    """Verify LSA creation and many-to-many skill mapping/back-population."""
    lsa = LSAProfile(
        name="John LSA",
        email="john.lsa@example.com",
        bio="Experienced educational support assistant.",
        hourly_rate=Decimal("35.00"),
    )
    skill1 = Skill(name="ADHD Support")
    skill2 = Skill(name="Autism Support")

    lsa.skills.extend([skill1, skill2])
    db.session.add_all([lsa, skill1, skill2])
    db.session.commit()

    assert lsa.id is not None
    assert len(lsa.skills) == 2
    assert skill1 in lsa.skills
    assert skill2 in lsa.skills
    
    # Test symmetric lookup via many-to-many backref
    assert len(skill1.lsas) == 1
    assert skill1.lsas[0] == lsa

def test_lsa_email_uniqueness(app):
    """Verify that multiple LSA profiles cannot share the same email."""
    lsa1 = LSAProfile(name="LSA One", email="lsa.dup@example.com", hourly_rate=Decimal("30.00"))
    db.session.add(lsa1)
    db.session.commit()

    lsa2 = LSAProfile(name="LSA Two", email="lsa.dup@example.com", hourly_rate=Decimal("30.00"))
    db.session.add(lsa2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_skill_name_uniqueness(app):
    """Verify Skill names are strictly unique."""
    skill1 = Skill(name="Behavior Support")
    db.session.add(skill1)
    db.session.commit()

    skill2 = Skill(name="Behavior Support")
    db.session.add(skill2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_booking_creation_and_relations(app):
    """Verify BookingRequest creation, foreign keys, and relationships."""
    parent = Parent(name="Alice Parent", email="alice@example.com")
    lsa = LSAProfile(name="John LSA", email="john@example.com", hourly_rate=Decimal("30.00"))
    db.session.add_all([parent, lsa])
    db.session.commit()

    now = datetime.now(timezone.utc)
    start_time = now + timedelta(hours=1)
    end_time = now + timedelta(hours=2)

    booking = BookingRequest(
        parent_id=parent.id,
        lsa_id=lsa.id,
        start_time=start_time,
        end_time=end_time,
        total_price=Decimal("30.00"),
    )
    db.session.add(booking)
    db.session.commit()

    assert booking.id is not None
    assert booking.parent == parent
    assert booking.lsa == lsa
    assert parent.bookings[0] == booking
    assert lsa.bookings[0] == booking

def test_booking_chronological_constraint(app):
    """Verify check constraint enforcing that start_time precedes end_time."""
    parent = Parent(name="Alice Parent", email="alice.constraint@example.com")
    lsa = LSAProfile(name="John LSA", email="john.constraint@example.com", hourly_rate=Decimal("30.00"))
    db.session.add_all([parent, lsa])
    db.session.commit()

    now = datetime.now(timezone.utc)
    start_time = now + timedelta(hours=2)
    end_time = now + timedelta(hours=1)  # end_time before start_time

    invalid_booking = BookingRequest(
        parent_id=parent.id,
        lsa_id=lsa.id,
        start_time=start_time,
        end_time=end_time,
        total_price=Decimal("30.00"),
    )
    db.session.add(invalid_booking)
    
    # SQLite/PostgreSQL raises an IntegrityError due to CheckConstraint violation
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_payment_booking_one_to_one(app):
    """Verify Payment's strict 1-to-1 relationship and constraints with BookingRequest."""
    parent = Parent(name="Alice Parent", email="alice.payment@example.com")
    lsa = LSAProfile(name="John LSA", email="john.payment@example.com", hourly_rate=Decimal("30.00"))
    db.session.add_all([parent, lsa])
    db.session.commit()

    now = datetime.now(timezone.utc)
    booking = BookingRequest(
        parent_id=parent.id,
        lsa_id=lsa.id,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        total_price=Decimal("30.00"),
    )
    db.session.add(booking)
    db.session.commit()

    # Link initial payment record
    payment = Payment(
        booking_id=booking.id,
        external_payment_id="pay_session_001",
        amount=Decimal("30.00"),
    )
    db.session.add(payment)
    db.session.commit()

    assert payment.id is not None
    assert booking.payment == payment
    assert payment.booking == booking

    # Check database-level uniqueness constraint by adding a second payment for the same booking
    duplicate_payment = Payment(
        booking_id=booking.id,
        external_payment_id="pay_session_002",
        amount=Decimal("30.00"),
    )
    db.session.add(duplicate_payment)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_payment_external_id_uniqueness(app):
    """Verify external payment identifiers are globally unique across all payments."""
    parent = Parent(name="Alice Parent", email="alice.payment.uniq@example.com")
    lsa = LSAProfile(name="John LSA", email="john.payment.uniq@example.com", hourly_rate=Decimal("30.00"))
    db.session.add_all([parent, lsa])
    db.session.commit()

    now = datetime.now(timezone.utc)
    booking1 = BookingRequest(
        parent_id=parent.id,
        lsa_id=lsa.id,
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        total_price=Decimal("30.00"),
    )
    booking2 = BookingRequest(
        parent_id=parent.id,
        lsa_id=lsa.id,
        start_time=now + timedelta(hours=3),
        end_time=now + timedelta(hours=4),
        total_price=Decimal("30.00"),
    )
    db.session.add_all([booking1, booking2])
    db.session.commit()

    pay1 = Payment(booking_id=booking1.id, external_payment_id="duplicate_ext_id", amount=Decimal("30.00"))
    db.session.add(pay1)
    db.session.commit()

    pay2 = Payment(booking_id=booking2.id, external_payment_id="duplicate_ext_id", amount=Decimal("30.00"))
    db.session.add(pay2)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
