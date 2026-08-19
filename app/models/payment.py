from datetime import datetime, timezone
from app.extensions import db

class Payment(db.Model):
    """Payment entity tracking transaction checkouts and payment processing states."""
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Unique foreign key forces 1-to-1 relationship with BookingRequest
    booking_id = db.Column(
        db.Integer,
        db.ForeignKey("booking_requests.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    # Unique, nullable external identifier for tracing webhook updates
    external_payment_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    currency = db.Column(db.String(3), default="USD", nullable=False)
    # Status: PENDING, SUCCESS, FAILED
    status = db.Column(db.String(20), default="PENDING", nullable=False)

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

    # Relationship back to BookingRequest
    booking = db.relationship("BookingRequest", back_populates="payment")

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} booking_id={self.booking_id} "
            f"status='{self.status}' external_id='{self.external_payment_id}'>"
        )
