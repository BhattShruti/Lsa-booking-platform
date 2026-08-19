"""
Rate Limiting Tests
===================
These tests explicitly enable rate limiting (disabled by default in TestingConfig).

Flask-Limiter 4.x reads RATELIMIT_ENABLED via config.setdefault() in init_app(),
so the enabled flag is captured at init time. To override it in tests, we must
re-call init_app() on the limiter after overriding the config value, OR use the
limiter's public API to directly mutate the enabled state and re-register the hooks.

The simplest correct approach: subclass TestingConfig with RATELIMIT_ENABLED=True
and create a fresh app with that config, then call limiter.init_app() again.
"""
import pytest
from flask import Flask
from app.config import TestingConfig
from app.extensions import db as _db, limiter, jwt, migrate, swagger
from app.utils.errors import register_error_handlers
from app.routes.auth import auth_bp
from app.routes.lsas import lsas_bp
from app.routes.bookings import bookings_bp
from app.routes.webhooks import webhooks_bp
from app.routes.health import health_bp
from app.routes.mock_gateway import mock_gateway_bp
from app.utils.logging import configure_logging


class RateLimitEnabledConfig(TestingConfig):
    """TestingConfig variant with rate limiting forced on and in-memory storage."""
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = "memory://"


@pytest.fixture
def rate_limited_app():
    """
    Builds a Flask app with rate limiting explicitly enabled.
    Re-initialises the limiter (which reads RATELIMIT_ENABLED at init_app time)
    so the enabled flag is captured correctly.
    """
    app = Flask(__name__)
    app.config.from_object(RateLimitEnabledConfig)

    configure_logging(app)

    # Re-init all extensions on this new app instance
    _db.init_app(app)
    migrate.init_app(app, _db)
    jwt.init_app(app)
    limiter.init_app(app)   # Reads RATELIMIT_ENABLED=True here
    swagger.init_app(app)

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(lsas_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(mock_gateway_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(auth_bp)

    register_error_handlers(app)

    with app.app_context():
        _db.create_all()
        yield app
        _db.session.rollback()
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def rate_limited_client(rate_limited_app):
    """Test client connected to the rate-limiting-enabled app."""
    return rate_limited_app.test_client()


class TestRegisterRateLimit:
    """Rate limit: 5 per minute on POST /api/v1/auth/register."""

    def test_register_blocked_after_limit(self, rate_limited_client):
        """After 5 requests, the 6th must receive 429."""
        url = "/api/v1/auth/register"

        # Send 5 requests (they may succeed or 400, but all consume quota)
        for i in range(5):
            rate_limited_client.post(
                url,
                json={"name": "Test", "email": f"rl_test{i}@example.com", "password": "pass"},
                content_type="application/json",
            )

        # 6th request must be rate-limited
        response = rate_limited_client.post(
            url,
            json={"name": "Test", "email": "rl_overflow@example.com", "password": "pass"},
            content_type="application/json",
        )
        assert response.status_code == 429

    def test_rate_limit_429_response_shape(self, rate_limited_client):
        """Verify the 429 response follows the project's standard error envelope."""
        url = "/api/v1/auth/register"
        for i in range(5):
            rate_limited_client.post(
                url,
                json={"name": "T", "email": f"rl_shape{i}@example.com", "password": "p"},
                content_type="application/json",
            )
        response = rate_limited_client.post(
            url,
            json={"name": "T", "email": "rl_shape6@example.com", "password": "p"},
            content_type="application/json",
        )
        assert response.status_code == 429
        body = response.get_json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"


class TestLoginRateLimit:
    """Rate limit: 5 per minute on POST /api/v1/auth/login."""

    def test_login_blocked_after_limit(self, rate_limited_client):
        """After 5 login attempts, the 6th must receive 429."""
        url = "/api/v1/auth/login"
        for _ in range(5):
            rate_limited_client.post(
                url,
                json={"email": "nobody@example.com", "password": "wrong"},
                content_type="application/json",
            )
        response = rate_limited_client.post(
            url,
            json={"email": "nobody@example.com", "password": "wrong"},
            content_type="application/json",
        )
        assert response.status_code == 429
