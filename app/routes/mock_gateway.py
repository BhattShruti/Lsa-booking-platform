from flask import Blueprint, request, jsonify

mock_gateway_bp = Blueprint("mock_gateway", __name__, url_prefix="/api/v1/mock-payment-gateway")

@mock_gateway_bp.route("/charge", methods=["POST"])
def charge():
    """
    Simulated external third-party payment gateway endpoint.
    Used for local testing and integration verification.
    """
    if not request.is_json:
        return jsonify({"error": "Request body must be a JSON payload"}), 400

    data = request.get_json()
    booking_id = data.get("booking_id")
    amount = data.get("amount")
    currency = data.get("currency")

    if not booking_id or amount is None or not currency:
        return jsonify({"error": "Missing required fields (booking_id, amount, currency)"}), 400

    # Deterministic simulation: If the amount ends in '.99', return a failed status
    amount_str = f"{amount:.2f}"
    if amount_str.endswith(".99"):
        return jsonify({
            "transaction_id": f"tx_declined_{booking_id}",
            "status": "FAILED",
            "reason": "Insufficient funds or card declined.",
        }), 200

    # Otherwise return a successful transaction ID
    return jsonify({
        "transaction_id": f"tx_success_{booking_id}",
        "status": "SUCCESS",
    }), 200
