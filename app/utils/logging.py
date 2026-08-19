import logging
import sys
from flask import Flask

def configure_logging(app: Flask) -> None:
    """Configure logging for the Flask application."""
    log_level_name = app.config.get("LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Standardized log format
    log_format = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s [%(pathname)s:%(lineno)d]: %(message)s"
    )

    # Configure stdout stream handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(log_format)
    handler.setLevel(log_level)

    # Clean existing handlers and add the standard stream handler
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)
    
    app.logger.info("Logging configured with level: %s", log_level_name)
