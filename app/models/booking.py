from datetime import datetime, timezone
from sqlalchemy import CheckConstraint
from app.extensions import db

class BookingRequest(db.Model):
    """BookingRequest entity tracking session schedules, statuses, and costs."""
    __tablename__ = "booking_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Foreign keys linking to clients and assistants
    parent_id = db.Column(db.Integer, db.ForeignKey("parents.id", ondelete="CASCADE"), nullable=False, index=True)
    lsa_id = db.Column(db.Integer, db.ForeignKey("lsa_profiles.id", ondelete="CASCADE"), nullable=False, index=True)

    # Session schedule
    start_time = db.Column(db.DateTime(timezone=True), nullable=False)
    end_time = db.Column(db.DateTime(timezone=True), nullable=False)

    # Status: PENDING, CONFIRMED, CANCELLED, FAILED
    status = db.Column(db.String(20), default="PENDING", nullable=False)
    # Computed cost (LSA rate * session duration)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    parent = db.relationship("Parent", back_populates="bookings")
    lsa = db.relationship("LSAProfile", back_populates="bookings")
    
    # 1-to-1 relationship with Payment. uselist=False guarantees the 1-to-1 mapping.
    payment = db.relationship("Payment", back_populates="booking", uselist=False, cascade="all, delete-orphan")

    # Table constraints and indexes
    __table_args__ = (
        # Ensure that start_time is chronologically before end_time
        CheckConstraint("start_time < end_time", name="check_start_before_end"),
        # Composite index for high-performance availability and overlap checks
        db.Index("idx_bookings_lsa_overlap", "lsa_id", "status", "start_time", "end_time"),
    )

    def __repr__(self) -> str:
        return (
            f"<BookingRequest id={self.id} parent_id={self.parent_id} "
            f"lsa_id={self.lsa_id} status='{self.status}'>"
        )
