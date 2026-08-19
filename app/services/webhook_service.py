from decimal import Decimal
import logging
from app.extensions import db
from app.models.booking import BookingRequest
from app.models.payment import Payment

logger = logging.getLogger(__name__)

class WebhookError(Exception):
    """Exception raised for webhook validation and processing errors."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

def process_payment_webhook(
    booking_id: int,
    external_payment_id: str,
    status: str,
    amount: Decimal,
    currency: str,
) -> dict:
    """
    Safely process and reconcile inbound payment webhooks.
    
    Safety and Design Features:
    1. Locks the BookingRequest row (`with_for_update()`) to prevent concurrent updates.
    2. Validates amount and currency against stored values using Decimal precision.
    3. Handles idempotency: if the payment is already in a final state, skips and returns 200 OK.
    4. Transitions Payment and BookingRequest statuses atomically in a database transaction.
    """
    # Use with_for_update on booking to serialize concurrent updates for the same booking request
    booking = db.session.query(BookingRequest).filter_by(id=booking_id).with_for_update().first()
    if not booking:
        logger.warning("Webhook received for non-existent booking_id=%d", booking_id)
        raise WebhookError(f"Booking with ID {booking_id} was not found.", 404)

    payment = booking.payment

    # Validate amount and currency
    expected_amount = payment.amount if payment else booking.total_price
    expected_currency = payment.currency if payment else "USD"

    # Monetary comparison using high-precision Decimal values
    if amount != expected_amount:
        logger.warning(
            "Webhook amount mismatch for booking_id=%d. Expected %s, received %s",
            booking_id, str(expected_amount), str(amount)
        )
        raise WebhookError("Payment amount mismatch.", 400)

    if currency.upper() != expected_currency.upper():
        logger.warning(
            "Webhook currency mismatch for booking_id=%d. Expected %s, received %s",
            booking_id, expected_currency, currency
        )
        raise WebhookError("Payment currency mismatch.", 400)

    # Initialize Payment record locally if it has not been created yet
    if not payment:
        payment = Payment(
            booking_id=booking_id,
            amount=booking.total_price,
            currency=expected_currency,
            status="PENDING",
        )
        db.session.add(payment)
        db.session.flush()

    # Idempotency check: if already transitioned to SUCCESS or FAILED, return success immediately
    if payment.status in ["SUCCESS", "FAILED"]:
        logger.info(
            "Idempotent webhook received for booking_id=%d. State is already '%s'.",
            booking_id, payment.status
        )
        return {
            "status": "success",
            "message": "Webhook processed (idempotent duplicate)",
            "booking_id": booking_id,
            "payment_status": payment.status,
            "booking_status": booking.status,
        }

    status_upper = status.upper()
    
    # Update states and record the external payment transaction reference
    if status_upper == "SUCCESS":
        payment.external_payment_id = external_payment_id
        payment.status = "SUCCESS"
        booking.status = "CONFIRMED"
        logger.info("Webhook transitioned booking_id=%d successfully to CONFIRMED/SUCCESS", booking_id)
    elif status_upper == "FAILED":
        payment.external_payment_id = external_payment_id
        payment.status = "FAILED"
        booking.status = "FAILED"
        logger.info("Webhook transitioned booking_id=%d successfully to FAILED/FAILED", booking_id)
    else:
        logger.warning("Webhook contains invalid status '%s' for booking_id=%d", status, booking_id)
        raise WebhookError(f"Unsupported status value: '{status}'", 400)

    return {
        "status": "success",
        "message": "State transitioned successfully",
        "booking_id": booking_id,
        "payment_status": payment.status,
        "booking_status": booking.status,
    }
