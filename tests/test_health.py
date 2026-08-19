from unittest.mock import patch
from sqlalchemy.exc import OperationalError


def test_app_creation(app):
    """Verify that the Flask application is correctly created in testing mode."""
    assert app is not None
    assert app.config["TESTING"] is True
    assert app.config["DEBUG"] is True


def test_health_check(client):
    """Verify that the /health liveness endpoint responds with 200 and structured JSON."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["status"] == "healthy"
    assert "message" in data


def test_centralized_error_handler_404(client):
    """Verify that accessing a non-existent URL returns a formatted JSON error response."""
    response = client.get("/invalid-url-path")
    assert response.status_code == 404

    data = response.get_json()
    assert data is not None
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]


# ── Readiness endpoint ─────────────────────────────────────────────────────────

def test_readiness_check_success(client):
    """GET /health/ready should return 200 with status=ready when DB is reachable."""
    response = client.get("/health/ready")
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data["status"] == "ready"
    assert data["database"] == "connected"


def test_readiness_check_response_shape(client):
    """Readiness response must include both 'status' and 'database' fields."""
    response = client.get("/health/ready")
    data = response.get_json()
    assert "status" in data
    assert "database" in data


def test_readiness_check_db_unavailable(client):
    """
    When the database is unavailable, GET /health/ready must return 503.
    The response body must NOT expose internal error details to the caller.
    """
    with patch("app.routes.health.db") as mock_db:
        # Simulate a DB connection failure
        mock_db.session.execute.side_effect = OperationalError(
            "connection refused", None, None
        )
        response = client.get("/health/ready")

    assert response.status_code == 503
    data = response.get_json()
    assert data is not None
    assert data["status"] == "not_ready"
    assert data["database"] == "unavailable"
    # Ensure internal DB details are not leaked to the caller
    assert "connection refused" not in str(data)


def test_liveness_does_not_require_db(client):
    """
    The /health liveness endpoint must return 200 even when DB is patched to fail,
    confirming it is a process-only check decoupled from database state.
    """
    with patch("app.routes.health.db") as mock_db:
        mock_db.session.execute.side_effect = OperationalError(
            "connection refused", None, None
        )
        response = client.get("/health")
    # Liveness should not touch the DB at all
    assert response.status_code == 200
