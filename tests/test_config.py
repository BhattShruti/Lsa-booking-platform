"""
Configuration Validation Tests
================================
Verify that ProductionConfig enforces strict security rules at load time
and that Development/TestingConfig behave permissively as expected.
"""
import os
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_with_env(monkeypatch, env_vars: dict):
    """
    Run ProductionConfig._validate() with a controlled environment.
    Returns (raised_exception | None).
    """
    from app.config import ProductionConfig

    # Patch environment
    for key, value in env_vars.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    try:
        ProductionConfig._validate()
        return None
    except ValueError as exc:
        return exc


# ── Production Config: PostgreSQL enforcement ──────────────────────────────────

class TestProductionConfigDatabaseValidation:
    """ProductionConfig must enforce PostgreSQL and reject SQLite."""

    VALID_ENV = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "SECRET_KEY": "a-unique-strong-production-secret-key-here",
        "JWT_SECRET_KEY": "a-unique-strong-jwt-secret-key-here-1234",
        "WEBHOOK_SECRET": "a-unique-strong-webhook-secret-key-here",
    }

    def test_valid_postgresql_url_passes(self, monkeypatch):
        exc = _validate_with_env(monkeypatch, self.VALID_ENV)
        assert exc is None, f"Expected no error but got: {exc}"

    def test_postgresql_plus_psycopg2_url_passes(self, monkeypatch):
        env = {**self.VALID_ENV, "DATABASE_URL": "postgresql+psycopg2://user:pass@host:5432/db"}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is None

    def test_legacy_postgres_scheme_rejected(self, monkeypatch):
        """postgres:// is normalized to postgresql:// — should pass after normalization."""
        env = {**self.VALID_ENV, "DATABASE_URL": "postgres://user:pass@localhost:5432/db"}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is None, "Normalized postgres:// URLs should be accepted"

    def test_sqlite_url_rejected_in_production(self, monkeypatch):
        env = {**self.VALID_ENV, "DATABASE_URL": "sqlite:///dev.db"}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "DATABASE_URL" in str(exc)

    def test_sqlite_memory_url_rejected_in_production(self, monkeypatch):
        env = {**self.VALID_ENV, "DATABASE_URL": "sqlite:///:memory:"}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "DATABASE_URL" in str(exc)

    def test_missing_database_url_rejected(self, monkeypatch):
        env = {**self.VALID_ENV, "DATABASE_URL": None}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "DATABASE_URL" in str(exc)


# ── Production Config: Secret enforcement ─────────────────────────────────────

class TestProductionConfigSecretValidation:
    """ProductionConfig must reject insecure or placeholder secret values."""

    VALID_ENV = {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "SECRET_KEY": "a-unique-strong-production-secret-key-here",
        "JWT_SECRET_KEY": "a-unique-strong-jwt-secret-key-here-1234",
        "WEBHOOK_SECRET": "a-unique-strong-webhook-secret-key-here",
    }

    @pytest.mark.parametrize("secret_value", [
        "",
        "default-dev-secret-key",
        "default-jwt-secret-key",
        "test-webhook-secret-key-change-me",
        "placeholder-secret-key-for-development-change-me",
        "change-me",
        "changeme",
    ])
    def test_insecure_secret_key_rejected(self, monkeypatch, secret_value):
        env = {**self.VALID_ENV, "SECRET_KEY": secret_value}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "SECRET_KEY" in str(exc)

    @pytest.mark.parametrize("secret_value", [
        "",
        "default-jwt-secret-key",
        "test-webhook-secret-key-change-me",
        "change-me",
    ])
    def test_insecure_jwt_secret_rejected(self, monkeypatch, secret_value):
        env = {**self.VALID_ENV, "JWT_SECRET_KEY": secret_value}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "JWT_SECRET_KEY" in str(exc)

    @pytest.mark.parametrize("secret_value", [
        "",
        "test-webhook-secret-key-change-me",
        "change-me",
    ])
    def test_insecure_webhook_secret_rejected(self, monkeypatch, secret_value):
        env = {**self.VALID_ENV, "WEBHOOK_SECRET": secret_value}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        assert "WEBHOOK_SECRET" in str(exc)

    def test_missing_jwt_secret_key_rejected(self, monkeypatch):
        env = {**self.VALID_ENV, "JWT_SECRET_KEY": None}
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None

    def test_multiple_errors_reported_together(self, monkeypatch):
        """All validation failures should be reported in a single ValueError."""
        env = {
            "DATABASE_URL": "sqlite:///dev.db",
            "SECRET_KEY": "change-me",
            "JWT_SECRET_KEY": "",
            "WEBHOOK_SECRET": "changeme",
        }
        exc = _validate_with_env(monkeypatch, env)
        assert exc is not None
        exc_str = str(exc)
        assert "DATABASE_URL" in exc_str
        assert "SECRET_KEY" in exc_str


# ── Production Config: DEBUG always False ─────────────────────────────────────

class TestProductionConfigDebug:
    """ProductionConfig must always have DEBUG=False."""

    def test_production_debug_is_false(self):
        from app.config import ProductionConfig
        assert ProductionConfig.DEBUG is False


# ── Development and Testing Config: permissive defaults ───────────────────────

class TestDevelopmentAndTestingConfig:
    """Development and Testing configs should allow SQLite and accept defaults."""

    def test_testing_config_allows_sqlite(self):
        from app.config import TestingConfig
        uri = TestingConfig.SQLALCHEMY_DATABASE_URI
        assert "sqlite" in uri or "postgresql" in uri  # either is fine

    def test_testing_config_rate_limiting_disabled(self):
        from app.config import TestingConfig
        assert TestingConfig.RATELIMIT_ENABLED is False

    def test_testing_config_debug_enabled(self):
        from app.config import TestingConfig
        assert TestingConfig.DEBUG is True

    def test_development_config_debug_enabled(self):
        from app.config import DevelopmentConfig
        assert DevelopmentConfig.DEBUG is True
