from datetime import datetime
from decimal import Decimal
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.booking import BookingRequest

class BookingServiceError(Exception):
    """Domain exception representing booking business logic errors."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

def create_booking(parent_id: int, lsa_id: int, start_time: datetime, end_time: datetime) -> BookingRequest:
    """
    Orchestrate creation of a new BookingRequest.
    
    Concurrency / Race-Condition Management:
    - Acquirers a pessimistic row-level write lock (`with_for_update()`) on the selected LSA Profile.
    - Any concurrent booking request attempting to allocate the same LSA will block on this lock.
    - While holding the lock, we execute validation and availability checks.
    - If valid, we insert the booking and flush the transaction. The database lock is released 
      once the transaction commits or rolls back in the calling controller layer.
    """
    # 1. Fetch LSA profile with row-level locking to serialize concurrent requests for this assistant
    lsa = db.session.query(LSAProfile).filter_by(id=lsa_id).with_for_update().first()
    
    if not lsa:
        raise BookingServiceError(
            code="LSA_NOT_FOUND",
            message=f"The requested LSA profile with ID {lsa_id} does not exist.",
            status_code=404,
        )
        
    if not lsa.is_active:
        raise BookingServiceError(
            code="LSA_INACTIVE",
            message=f"The LSA profile with ID {lsa_id} is currently inactive and cannot be booked.",
            status_code=400,
        )

    # 2. Fetch Parent profile
    parent = db.session.get(Parent, parent_id)
    if not parent:
        raise BookingServiceError(
            code="PARENT_NOT_FOUND",
            message=f"The parent profile with ID {parent_id} does not exist.",
            status_code=404,
        )

    # 3. Check for overlapping bookings (excluding CANCELLED and FAILED bookings)
    # Overlap logic: existing.start_time < requested.end_time AND existing.end_time > requested.start_time
    has_overlap = db.session.query(BookingRequest.id).filter(
        BookingRequest.lsa_id == lsa_id,
        BookingRequest.status.in_(["PENDING", "CONFIRMED"]),
        BookingRequest.start_time < end_time,
        BookingRequest.end_time > start_time
    ).first() is not None

    if has_overlap:
        raise BookingServiceError(
            code="BOOKING_CONFLICT",
            message="The requested LSA is already booked during the specified time period.",
            status_code=409,
        )

    # 4. Calculate total price using high-precision Decimal arithmetic
    duration_seconds = (end_time - start_time).total_seconds()
    duration_hours = Decimal(duration_seconds) / Decimal(3600)
    total_price = (lsa.hourly_rate * duration_hours).quantize(Decimal("0.01"))

    # 5. Build and save the booking request
    booking = BookingRequest(
        parent_id=parent_id,
        lsa_id=lsa_id,
        start_time=start_time,
        end_time=end_time,
        status="PENDING",
        total_price=total_price,
    )
    db.session.add(booking)
    db.session.flush()  # Generate the ID within current transaction block

    return booking
