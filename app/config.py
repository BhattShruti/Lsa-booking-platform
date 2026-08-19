import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

# ------------------------------------------------------------------ #
# Placeholder/insecure default values that must NOT be used in prod  #
# ------------------------------------------------------------------ #
_INSECURE_SECRET_VALUES = {
    '',
    'default-dev-secret-key',
    'default-jwt-secret-key',
    'test-webhook-secret-key-change-me',
    'placeholder-secret-key-for-development-change-me',
    'local-dev-secret-key-change-me-in-production',
    'test-secret-key-for-ci',
    'change-me',
    'changeme',
}


def _normalize_db_url(url: str) -> str:
    """Normalize legacy 'postgres://' scheme to 'postgresql://' for SQLAlchemy 1.4+."""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _is_postgresql_url(url: str) -> bool:
    """Return True if the URL scheme is a supported PostgreSQL scheme."""
    if not url:
        return False
    try:
        scheme = urlparse(url).scheme
    except Exception:
        return False
    return scheme in ("postgresql", "postgresql+psycopg2", "postgresql+asyncpg",
                      "postgresql+pg8000", "postgresql+psycopg")


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-dev-secret-key')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'default-jwt-secret-key')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')

    # Database URL – normalize legacy scheme at class level
    _raw_db_url = os.environ.get('DATABASE_URL') or 'sqlite:///dev.db'
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(_raw_db_url)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Logging level
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

    # Mock external service URL for payment integrations
    MOCK_PAYMENT_URL = os.environ.get(
        'MOCK_PAYMENT_URL',
        'http://localhost:5000/api/v1/mock-payment-gateway/charge'
    )

    # Webhook signature secret key for HMAC validation
    WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', 'test-webhook-secret-key-change-me')
    WEBHOOK_TOLERANCE = int(os.environ.get('WEBHOOK_TOLERANCE', 300))

    # Pagination Configuration
    PAGINATION_MAX_PER_PAGE = int(os.environ.get('PAGINATION_MAX_PER_PAGE', 50))
    PAGINATION_DEFAULT_PER_PAGE = 10

    # Rate Limiting Configuration
    RATELIMIT_ENABLED = True


class DevelopmentConfig(Config):
    """Development configuration — SQLite or Postgres, DEBUG on."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get('DATABASE_URL', 'sqlite:///dev.db')
    )


class TestingConfig(Config):
    """Testing configuration — in-memory SQLite (fast, isolated), rate limiting off."""
    TESTING = True
    DEBUG = True
    RATELIMIT_ENABLED = False
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
    )


class ProductionConfig(Config):
    """
    Production configuration.

    Startup validation rules (fail-fast):
    - DATABASE_URL must point to PostgreSQL.
    - SECRET_KEY, JWT_SECRET_KEY, and WEBHOOK_SECRET must be explicitly set
      to non-placeholder values via environment variables.
    - DEBUG is always False.
    """
    DEBUG = False

    # ---- Secret validation ---------------------------------------- #
    @classmethod
    def _validate(cls) -> None:
        """Raise ValueError for any unsafe production configuration."""
        errors: list[str] = []

        db_url = _normalize_db_url(os.environ.get('DATABASE_URL', ''))
        if not db_url or not _is_postgresql_url(db_url):
            errors.append(
                "DATABASE_URL must be a PostgreSQL connection string "
                "(e.g. postgresql://user:pass@host:5432/db). "
                f"Got: '{db_url or '(not set)'}'"
            )

        for var, attr in [
            ('SECRET_KEY', 'SECRET_KEY'),
            ('JWT_SECRET_KEY', 'JWT_SECRET_KEY'),
            ('WEBHOOK_SECRET', 'WEBHOOK_SECRET'),
        ]:
            value = os.environ.get(var, '')
            if not value or value.strip().lower() in _INSECURE_SECRET_VALUES:
                errors.append(
                    f"{var} must be set to a strong secret value in production. "
                    "Set it via the environment variable."
                )

        if errors:
            raise ValueError(
                "ProductionConfig validation failed — unsafe or missing configuration:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )


# ------------------------------------------------------------------ #
# Run production validation immediately when this class is loaded    #
# (only when FLASK_ENV=production to avoid breaking tests/dev)       #
# ------------------------------------------------------------------ #
if os.environ.get('FLASK_ENV') == 'production':
    ProductionConfig._validate()


# Dictionary to map environment name to config class
config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
}

