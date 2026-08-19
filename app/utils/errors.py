from flask import jsonify, current_app
from werkzeug.exceptions import HTTPException

def register_error_handlers(app):
    """Register centralized error handlers on the Flask application."""

    @app.errorhandler(429)
    def handle_rate_limit_exceeded(e):
        """Handle rate limit exceeded exception."""
        return jsonify({
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "Rate limit exceeded. Please try again later."
            }
        }), 429

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Handle standard HTTP exceptions (e.g., 404, 405, 400)."""
        response = {
            "error": {
                "code": getattr(e, "name", "HTTP_EXCEPTION").replace(" ", "_").upper(),
                "message": e.description
            }
        }
        return jsonify(response), e.code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e):
        """Handle unexpected runtime exceptions (500 Internal Server Error)."""
        # Log the full exception traceback
        current_app.logger.exception(f"Unhandled exception encountered: {str(e)}")

        response = {
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred on the server."
            }
        }
        # Include detailed error message only when debugging is active
        if current_app.config.get("DEBUG", False):
            response["error"]["details"] = str(e)

        return jsonify(response), 500
