from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required
from sqlalchemy import func
from app.extensions import db, limiter
from app.models.parent import Parent
from app.utils.auth import get_authenticated_parent

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

@auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    """
    Register a new parent account.
    ---
    tags:
      - Authentication
    summary: Register a new parent
    description: >
      Creates a new parent profile with a securely hashed password.
      Email addresses are normalized to lowercase and must be unique.
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - name
              - email
              - password
            properties:
              name:
                type: string
                example: Jane Doe
              email:
                type: string
                format: email
                example: jane@example.com
              password:
                type: string
                format: password
                example: securepassword123
    responses:
      201:
        description: Parent profile created successfully.
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
                    name:
                      type: string
                    email:
                      type: string
                    created_at:
                      type: string
                      format: date-time
      400:
        description: Validation error or duplicate email.
      429:
        description: Rate limit exceeded.
    """
    if not request.is_json:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a valid JSON payload."
            }
        }), 400

    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    missing = []
    if not name:
        missing.append("name")
    if not email:
        missing.append("email")
    if not password:
        missing.append("password")

    if missing:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": f"Missing required fields: {', '.join(missing)}"
            }
        }), 400

    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "name must be a non-empty string."}}), 400
    if not isinstance(email, str) or not email.strip():
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "email must be a non-empty string."}}), 400
    if not isinstance(password, str) or not password.strip():
        return jsonify({"error": {"code": "BAD_REQUEST", "message": "password must be a non-empty string."}}), 400

    # Normalize email to lowercase
    normalized_email = email.strip().lower()

    # Case-insensitive duplicate email check
    existing_parent = db.session.query(Parent).filter(
        func.lower(Parent.email) == normalized_email
    ).first()

    if existing_parent:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "A parent profile with this email address already exists."
            }
        }), 400

    parent = Parent(name=name.strip(), email=normalized_email)
    parent.set_password(password)

    db.session.add(parent)
    db.session.commit()

    return jsonify({
        "data": {
            "id": parent.id,
            "name": parent.name,
            "email": parent.email,
            "created_at": parent.created_at.isoformat()
        }
    }), 201

@auth_bp.route("/login", methods=["POST"])
@limiter.limit("5 per minute")
def login():
    """
    Authenticate a parent and issue a JWT access token.
    ---
    tags:
      - Authentication
    summary: Login and get JWT token
    description: >
      Validates parent credentials and returns a signed JWT access token
      for use in subsequent authenticated requests.
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required:
              - email
              - password
            properties:
              email:
                type: string
                format: email
                example: jane@example.com
              password:
                type: string
                format: password
                example: securepassword123
    responses:
      200:
        description: Successful login; returns JWT access token.
        content:
          application/json:
            schema:
              type: object
              properties:
                access_token:
                  type: string
      400:
        description: Missing or invalid credentials format.
      401:
        description: Invalid email or password.
      429:
        description: Rate limit exceeded.
    """
    if not request.is_json:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Request body must be a valid JSON payload."
            }
        }), 400

    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "Missing email or password."
            }
        }), 400

    normalized_email = str(email).strip().lower()
    parent = db.session.query(Parent).filter(
        func.lower(Parent.email) == normalized_email
    ).first()

    if not parent or not parent.check_password(str(password)):
        return jsonify({
            "error": {
                "code": "UNAUTHORIZED",
                "message": "Invalid email or password."
            }
        }), 401

    access_token = create_access_token(identity=str(parent.id))
    return jsonify({
        "access_token": access_token
    }), 200

@auth_bp.route("/me", methods=["GET"])
@jwt_required()
@limiter.limit("20 per minute")
def me():
    """
    Retrieve the authenticated parent's profile.
    ---
    tags:
      - Authentication
    summary: Get current parent profile
    description: Returns the profile of the currently authenticated parent, identified by the JWT.
    security:
      - BearerAuth: []
    responses:
      200:
        description: Parent profile returned successfully.
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
                    name:
                      type: string
                    email:
                      type: string
                    created_at:
                      type: string
                      format: date-time
      401:
        description: Missing or invalid JWT token.
      429:
        description: Rate limit exceeded.
    """
    parent = get_authenticated_parent()
    return jsonify({
        "data": {
            "id": parent.id,
            "name": parent.name,
            "email": parent.email,
            "created_at": parent.created_at.isoformat()
        }
    }), 200
