from flask import Blueprint, jsonify, current_app
from sqlalchemy import text
from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health_check():
    """
    Liveness probe — confirms the Flask process is alive.
    ---
    tags:
      - Health
    summary: Liveness check
    description: |
      Lightweight liveness probe. Returns 200 OK if the Flask process is
      running. Does NOT check database connectivity.
    responses:
      200:
        description: Application process is alive.
        schema:
          type: object
          properties:
            status:
              type: string
              example: healthy
            message:
              type: string
    """
    return jsonify({
        "status": "healthy",
        "message": "HabotConnect LSA Service Booking API is running"
    }), 200


@health_bp.route("/health/ready", methods=["GET"])
def readiness_check():
    """
    Readiness probe — confirms the application can serve database-backed requests.
    ---
    tags:
      - Health
    summary: Readiness check (includes database connectivity)
    description: |
      Executes a lightweight SELECT 1 against the configured database.
      Returns 200 when the database is reachable and the application is ready
      to serve traffic. Returns 503 when the database is unavailable.
      Use this as the Docker/load-balancer healthcheck target.
    responses:
      200:
        description: Application is ready to serve requests.
        schema:
          type: object
          properties:
            status:
              type: string
              example: ready
            database:
              type: string
              example: connected
      503:
        description: Application is not ready — database is unavailable.
        schema:
          type: object
          properties:
            status:
              type: string
              example: not_ready
            database:
              type: string
              example: unavailable
    """
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({
            "status": "ready",
            "database": "connected"
        }), 200
    except Exception as exc:
        current_app.logger.error("Readiness check failed — DB unavailable: %s", exc)
        return jsonify({
            "status": "not_ready",
            "database": "unavailable"
        }), 503
