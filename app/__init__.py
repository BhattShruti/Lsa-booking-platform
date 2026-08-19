import os
from flask import Flask
from app.config import config_by_name
from app.extensions import db, migrate, jwt, limiter, swagger
from app.routes.health import health_bp
from app.routes.lsas import lsas_bp
from app.routes.bookings import bookings_bp
from app.routes.mock_gateway import mock_gateway_bp
from app.routes.webhooks import webhooks_bp
from app.routes.auth import auth_bp
from app.utils.errors import register_error_handlers
from app.utils.logging import configure_logging
from app import models

def create_app(config_name: str = None) -> Flask:
    """Application factory to construct, configure, and initialize the Flask application."""
    # Retrieve configuration type from environment if not specified
    if not config_name:
        config_name = os.environ.get("FLASK_ENV", "development")

    app = Flask(__name__)

    # Load configuration class matching the config_name
    config_class = config_by_name.get(config_name, config_by_name["development"])
    app.config.from_object(config_class)

    # Initialize logging prior to extensions so config log levels apply
    configure_logging(app)
    app.logger.info("Initializing HabotConnect LSA API in [%s] configuration context", config_name)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)
    swagger.init_app(app)

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(lsas_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(mock_gateway_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(auth_bp)

    # Register error handlers
    register_error_handlers(app)

    # Register CLI commands
    from app.utils.seed import seed_db

    @app.cli.command("seed")
    def seed_command():
        """Seed the database with development data."""
        seed_db()
        app.logger.info("Database successfully seeded.")

    return app
