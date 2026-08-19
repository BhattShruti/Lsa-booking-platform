import logging
import requests
from flask import current_app
from app.extensions import db
from app.models.booking import BookingRequest
from app.models.payment import Payment

logger = logging.getLogger(__name__)

class PaymentGatewayError(Exception):
    """Exception raised for payments gateway integration failures."""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

def process_booking_payment(booking_id: int) -> Payment:
    """
    Process payment for a booking request by calling the mock external payment gateway.
    
    Ensures:
    1. The booking exists and is in a PENDING state.
    2. A local Payment record exists (or is created) in PENDING state.
    3. Calls the external gateway using `requests.post` with an explicit timeout.
    4. Handles timeouts, connection errors, and response failures.
    5. Updates the local Payment state and Booking state accordingly inside a transaction.
    """
    gateway_url = current_app.config.get("MOCK_PAYMENT_URL")
    if not gateway_url:
        logger.error("Configuration error: MOCK_PAYMENT_URL is not set.")
        raise PaymentGatewayError("Payment gateway configuration is missing on the server.", 500)

    # 1. Fetch booking
    booking = db.session.get(BookingRequest, booking_id)
    if not booking:
        raise PaymentGatewayError(f"Booking request with ID {booking_id} was not found.", 404)
        
    if booking.status != "PENDING":
        raise PaymentGatewayError(
            f"Booking with ID {booking_id} is in '{booking.status}' state. "
            "Payments can only be processed for PENDING bookings.", 
            400
        )

    # 2. Get or initialize the local Payment record
    payment = booking.payment
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            amount=booking.total_price,
            status="PENDING"
        )
        db.session.add(payment)
        db.session.flush()

    # Idempotency check: if payment already succeeded, avoid double-charging
    if payment.status == "SUCCESS":
        logger.info("Payment already succeeded for booking_id=%d. Skipping gateway call.", booking_id)
        return payment

    # 3. Call the external service via HTTP POST using requests
    payload = {
        "booking_id": booking.id,
        "amount": float(payment.amount),
        "currency": payment.currency
    }

    logger.info("Initiating external payment request: booking_id=%d, amount=%s", booking.id, str(payment.amount))
    
    timeout = 5.0  # 5-second timeout as requested
    
    try:
        response = requests.post(gateway_url, json=payload, timeout=timeout)
        
        logger.info("External payment gateway response: status_code=%d for booking_id=%d", response.status_code, booking.id)
        
        if response.status_code == 200:
            try:
                response_data = response.json()
            except ValueError:
                logger.error("External payment gateway returned invalid JSON for booking_id=%d", booking.id)
                # Mark as FAILED on malformed response
                payment.status = "FAILED"
                booking.status = "FAILED"
                db.session.commit()
                raise PaymentGatewayError("The payment gateway returned an unparseable response.", 502)
                
            transaction_id = response_data.get("transaction_id")
            status = response_data.get("status")
            
            if not transaction_id or not status:
                logger.error("External payment gateway response is missing required fields for booking_id=%d", booking.id)
                payment.status = "FAILED"
                booking.status = "FAILED"
                db.session.commit()
                raise PaymentGatewayError("The payment gateway returned a malformed response.", 502)
                
            if status == "SUCCESS":
                payment.external_payment_id = transaction_id
                payment.status = "SUCCESS"
                booking.status = "CONFIRMED"
                logger.info("Payment successfully processed: booking_id=%d, tx_id=%s", booking.id, transaction_id)
            else:
                payment.external_payment_id = transaction_id
                payment.status = "FAILED"
                booking.status = "FAILED"
                logger.warning(
                    "Payment declined by gateway: booking_id=%d, tx_id=%s, reason=%s", 
                    booking.id, transaction_id, response_data.get("reason", "unknown")
                )
            
            db.session.commit()
            return payment
            
        else:
            logger.error("External payment gateway returned HTTP error=%d for booking_id=%d", response.status_code, booking.id)
            payment.status = "FAILED"
            booking.status = "FAILED"
            db.session.commit()
            raise PaymentGatewayError("The payment gateway returned an error status.", 502)

    except requests.Timeout:
        logger.error("External payment request timed out (timeout=%fs) for booking_id=%d", timeout, booking.id)
        payment.status = "FAILED"
        booking.status = "FAILED"
        db.session.commit()
        raise PaymentGatewayError("Connection to the payment gateway timed out.", 504)
        
    except requests.ConnectionError:
        logger.error("External payment connection failed for booking_id=%d", booking.id)
        payment.status = "FAILED"
        booking.status = "FAILED"
        db.session.commit()
        raise PaymentGatewayError("Could not establish connection to the payment gateway.", 502)
        
    except requests.RequestException as e:
        logger.error("External payment request encountered a failure for booking_id=%d: %s", booking.id, str(e))
        payment.status = "FAILED"
        booking.status = "FAILED"
        db.session.commit()
        raise PaymentGatewayError("The payment gateway request failed to execute.", 502)
