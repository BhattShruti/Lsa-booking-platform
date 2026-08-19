from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.extensions import db, limiter
from app.services.booking_service import create_booking, BookingServiceError
from app.models.booking import BookingRequest
from app.utils.auth import get_authenticated_parent, verify_booking_ownership


bookings_bp = Blueprint("bookings", __name__, url_prefix="/api/v1/bookings")

def parse_iso_datetime(value: str) -> datetime:
    """
    Parse an ISO-8601 datetime string.
    Supports trailing 'Z' by converting it to '+00:00' for compatibility with Python 3.10.
    """
    if not value or not value.strip():
        raise ValueError("Datetime string cannot be empty")

    val = value.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Invalid ISO-8601 datetime format: '{value}'")

@bookings_bp.route("/", methods=["POST"])
@jwt_required()
@limiter.limit("10 per minute")
def create_booking_route():
    """
    Create a new booking for an LSA.
    ---
    tags:
      - Bookings
    summary: Create a booking
    description: >
      Creates a new booking for the authenticated parent.
      Parent identity is derived exclusively from the JWT — client-supplied
      parent_id is explicitly rejected. Prevents double-booking via pessimistic locking.
    security:
      - BearerAuth: []
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - lsa_id
              - start_time
              - end_time
            properties:
              lsa_id:
                type: integer
                example: 1
              start_time:
                type: string
                format: date-time
                example: "2026-08-15T10:00:00Z"
              end_time:
                type: string
                format: date-time
                example: "2026-08-15T11:00:00Z"
    responses:
      201:
        description: Booking created successfully.
        content:
          application/json:
            schema:
              type: object
              properties:
                data:
                  type: object
                  properties:
                    id:
                      type: integer
                    parent_id:
                      type: integer
                    lsa_id:
                      type: integer
                    start_time:
                      type: string
                      format: date-time
                    end_time:
                      type: string
                      format: date-time
                    status:
                      type: string
                    total_price:
                      type: number
      400:
        description: Validation error or booking conflict.
      401:
        description: Missing or invalid JWT token.
      429:
        description: Rate limit exceeded.
    """
    # 1. Verify JSON payload type
    if not request.is_json:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a valid JSON payload."
            }
        }), 400

    data = request.get_json()

    # Enforce parent_id rejection: client must not specify parent identity
    if "parent_id" in data:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "parent_id is not allowed in the request body. User identity is derived from the authentication token."
            }
        }), 400

    # 2. Check for required parameters
    required_fields = ["lsa_id", "start_time", "end_time"]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Missing required fields: {', '.join(missing_fields)}"
            }
        }), 400

    # Fetch active parent identity securely
    parent = get_authenticated_parent()
    parent_id = parent.id

    lsa_id = data.get("lsa_id")
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")

    errors = []

    # 3. Validate types of identifiers
    if not isinstance(lsa_id, int):
        errors.append("lsa_id must be an integer")

    # 4. Parse dates
    start_dt = None
    if isinstance(start_time_str, str):
        try:
            start_dt = parse_iso_datetime(start_time_str)
        except ValueError as e:
            errors.append(str(e))
    else:
        errors.append("start_time must be a string")

    end_dt = None
    if isinstance(end_time_str, str):
        try:
            end_dt = parse_iso_datetime(end_time_str)
        except ValueError as e:
            errors.append(str(e))
    else:
        errors.append("end_time must be a string")

    if errors:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "; ".join(errors)
            }
        }), 400

    # 5. Chronological order validation
    if start_dt >= end_dt:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "start_time must be chronologically before end_time"
            }
        }), 400

    # 6. Execute booking creation and handle transaction boundaries
    try:
        booking = create_booking(parent_id, lsa_id, start_dt, end_dt)
        db.session.commit()
    except BookingServiceError as e:
        db.session.rollback()
        return jsonify({
            "error": {
                "code": e.code,
                "message": e.message
            }
        }), e.status_code
    except Exception as e:
        db.session.rollback()
        # central logging intercepts this and issues standard 500 error response
        raise e

    # 7. Return success response
    return jsonify({
        "data": {
            "id": booking.id,
            "parent_id": booking.parent_id,
            "lsa_id": booking.lsa_id,
            "start_time": booking.start_time.isoformat(),
            "end_time": booking.end_time.isoformat(),
            "status": booking.status,
            "total_price": float(booking.total_price),
        }
    }), 201

@bookings_bp.route("/<int:booking_id>/pay", methods=["POST"])
@jwt_required()
@limiter.limit("10 per minute")
def pay_booking_route(booking_id):
    """
    Initiate payment for a booking.
    ---
    tags:
      - Bookings
    summary: Pay for a booking
    description: >
      Initiates an outbound payment request to the external mock payment gateway
      for the specified booking. Ownership is verified — only the booking owner
      may pay.
    security:
      - BearerAuth: []
    parameters:
      - name: booking_id
        in: path
        required: true
        schema:
          type: integer
        description: The ID of the booking to pay for.
    responses:
      200:
        description: Payment initiated successfully.
        content:
          application/json:
            schema:
              type: object
              properties:
                data:
                  type: object
                  properties:
                    booking_id:
                      type: integer
                    payment_id:
                      type: integer
                    amount:
                      type: number
                    currency:
                      type: string
                    status:
                      type: string
                    external_payment_id:
                      type: string
      401:
        description: Missing or invalid JWT token.
      403:
        description: Forbidden — booking does not belong to authenticated parent.
      404:
        description: Booking not found.
      429:
        description: Rate limit exceeded.
    """
    # 1. Fetch booking first to verify existence and check ownership
    booking = db.session.get(BookingRequest, booking_id)
    if not booking:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": f"Booking request with ID {booking_id} was not found."
            }
        }), 404

    # 2. Verify identity and authorization
    parent = get_authenticated_parent()
    verify_booking_ownership(booking, parent)

    try:
        from app.services.payment_service import process_booking_payment, PaymentGatewayError
        payment = process_booking_payment(booking_id)
        return jsonify({
            "data": {
                "booking_id": payment.booking_id,
                "payment_id": payment.id,
                "amount": float(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "external_payment_id": payment.external_payment_id
            }
        }), 200
    except PaymentGatewayError as e:
        return jsonify({
            "error": {
                "code": "PAYMENT_GATEWAY_ERROR",
                "message": e.message
            }
        }), e.status_code
