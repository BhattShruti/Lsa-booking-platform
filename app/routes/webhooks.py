import hmac
import hashlib
import json
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify, current_app
from app.extensions import db
from app.services.webhook_service import process_payment_webhook, WebhookError

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/payments")

@webhooks_bp.route("/webhook/", methods=["POST"])
def payments_webhook():
    """
    Process payment webhook from the external gateway.
    ---
    tags:
      - Webhooks
    summary: Receive payment status webhook
    description: >
      Accepts inbound payment status notifications from the external payment gateway.
      Secured via HMAC-SHA256 signature verification and timestamp replay protection.
      The signed message format is: "{timestamp}.{raw_payload}".
      Timestamps outside the configured tolerance window (default 300s) are rejected.
      Delivery is idempotent — duplicate events for the same external_payment_id are safely ignored.
    parameters:
      - name: X-Webhook-Signature
        in: header
        required: true
        schema:
          type: string
        description: HMAC-SHA256 hex digest of "{timestamp}.{raw_payload}" using the shared secret.
      - name: X-Webhook-Timestamp
        in: header
        required: true
        schema:
          type: integer
        description: Unix epoch timestamp (seconds) of when the request was signed.
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - booking_id
              - external_payment_id
              - status
              - amount
              - currency
            properties:
              booking_id:
                type: integer
                example: 1
              external_payment_id:
                type: string
                example: "txn_success_123"
              status:
                type: string
                enum: [SUCCESS, FAILED]
                example: "SUCCESS"
              amount:
                type: number
                example: 50.00
              currency:
                type: string
                example: "USD"
    responses:
      200:
        description: Webhook processed successfully (or idempotent duplicate acknowledged).
      400:
        description: Malformed payload or validation error.
      401:
        description: Missing, expired, future, or invalid HMAC signature.
      500:
        description: Webhook secret not configured.
    """
    # 1. Signature & Timestamp Verification
    signature = request.headers.get("X-Webhook-Signature")
    timestamp_str = request.headers.get("X-Webhook-Timestamp")
    
    if not signature:
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Missing webhook signature."
            }
        }), 401

    if not timestamp_str:
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Missing webhook timestamp."
            }
        }), 401

    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Invalid webhook timestamp format."
            }
        }), 400

    import time
    current_time = int(time.time())
    tolerance = current_app.config.get("WEBHOOK_TOLERANCE", 300)
    
    # Check if timestamp is outside of the tolerance window (both past and future)
    if abs(current_time - timestamp) > tolerance:
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Webhook timestamp is outside of the allowed tolerance window."
            }
        }), 401

    secret = current_app.config.get("WEBHOOK_SECRET")
    if not secret:
        return jsonify({
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Webhook verification secret is not configured."
            }
        }), 500

    raw_data = request.get_data()
    raw_data_str = raw_data.decode("utf-8") if isinstance(raw_data, bytes) else raw_data
    
    # Sign format: message = f"{timestamp}.{raw_payload}"
    message = f"{timestamp_str}.{raw_data_str}"
    calculated_sig = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_sig, signature):
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid webhook signature."
            }
        }), 401

    # 2. Decode raw JSON payload
    try:
        data = json.loads(raw_data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a valid JSON payload."
            }
        }), 400

    # 3. Check for required parameters
    required_fields = ["booking_id", "external_payment_id", "status", "amount", "currency"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Missing required fields: {', '.join(missing_fields)}"
            }
        }), 400

    booking_id = data.get("booking_id")
    external_payment_id = data.get("external_payment_id")
    status = data.get("status")
    amount_raw = data.get("amount")
    currency = data.get("currency")

    errors = []

    # 2. Type validation
    if not isinstance(booking_id, int):
        errors.append("booking_id must be an integer")
    if not isinstance(external_payment_id, str) or not external_payment_id.strip():
        errors.append("external_payment_id must be a non-empty string")
    if not isinstance(status, str) or not status.strip():
        errors.append("status must be a non-empty string")
    if not isinstance(currency, str) or not currency.strip():
        errors.append("currency must be a non-empty string")

    # 3. Parse amount to high-precision Decimal
    amount = None
    try:
        amount = Decimal(str(amount_raw))
    except (ValueError, TypeError, InvalidOperation):
        errors.append("amount must be a valid decimal number")

    if errors:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "; ".join(errors)
            }
        }), 400

    # 4. Process webhook within atomic transaction boundaries
    try:
        result = process_payment_webhook(
            booking_id=booking_id,
            external_payment_id=external_payment_id,
            status=status,
            amount=amount,
            currency=currency,
        )
        db.session.commit()
        return jsonify(result), 200
    except WebhookError as e:
        db.session.rollback()
        return jsonify({
            "error": {
                "code": "WEBHOOK_PROCESSING_ERROR",
                "message": e.message
            }
        }), e.status_code
    except Exception as e:
        db.session.rollback()
        # Central error handler catches unexpected exceptions, logs and sends 500
        raise e
