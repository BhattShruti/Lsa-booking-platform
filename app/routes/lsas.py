from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from app.extensions import limiter
from app.services.lsa_service import search_available_lsas

lsas_bp = Blueprint("lsas", __name__, url_prefix="/api/v1/lsas")

def parse_iso_datetime(value: str) -> datetime:
    """
    Parse an ISO-8601 datetime string.
    Supports trailing 'Z' by converting it to '+00:00' for compatibility with Python 3.10.
    """
    if not value or not value.strip():
        raise ValueError("Datetime string cannot be empty")
    
    val = value.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(val)
        # Normalize timezone-naive timestamps to UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise ValueError(f"Invalid ISO-8601 datetime format: '{value}'")

@lsas_bp.route("/search", methods=["GET"])
@lsas_bp.route("/search/", methods=["GET"])
@limiter.limit("10 per minute")
def search_lsas():
    """
    Search available active LSAs filtered by skill and time slot, with pagination.
    ---
    tags:
      - LSAs
    summary: Search available LSAs
    description: >
      Returns a paginated list of active LSAs possessing the requested skill
      and available (no overlapping bookings) during the given time window.
      Results are ordered by LSA ID ascending for stable pagination.
    parameters:
      - name: skill
        in: query
        required: true
        schema:
          type: string
        description: Skill name to filter by (case-insensitive).
        example: Mathematics
      - name: start_time
        in: query
        required: true
        schema:
          type: string
          format: date-time
        description: Start of the availability window (ISO-8601).
        example: "2026-08-15T10:00:00Z"
      - name: end_time
        in: query
        required: true
        schema:
          type: string
          format: date-time
        description: End of the availability window (ISO-8601).
        example: "2026-08-15T11:00:00Z"
      - name: page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          default: 1
        description: Page number (1-indexed).
      - name: per_page
        in: query
        required: false
        schema:
          type: integer
          minimum: 1
          maximum: 50
          default: 10
        description: Number of results per page (max 50).
    responses:
      200:
        description: Paginated list of available LSAs.
        content:
          application/json:
            schema:
              type: object
              properties:
                data:
                  type: array
                  items:
                    type: object
                    properties:
                      id:
                        type: integer
                      name:
                        type: string
                      bio:
                        type: string
                      hourly_rate:
                        type: number
                      skills:
                        type: array
                        items:
                          type: string
                pagination:
                  type: object
                  properties:
                    page:
                      type: integer
                    per_page:
                      type: integer
                    total:
                      type: integer
                    pages:
                      type: integer
                    has_next:
                      type: boolean
                    has_prev:
                      type: boolean
      400:
        description: Validation error.
    """
    skill = request.args.get("skill")
    start_time_str = request.args.get("start_time")
    end_time_str = request.args.get("end_time")

    # Pagination parameters
    max_per_page = current_app.config.get("PAGINATION_MAX_PER_PAGE", 50)
    default_per_page = current_app.config.get("PAGINATION_DEFAULT_PER_PAGE", 10)

    errors = []

    # Parse page
    page = 1
    page_str = request.args.get("page", "1")
    try:
        page = int(page_str)
        if page < 1:
            errors.append("Parameter 'page' must be a positive integer")
    except ValueError:
        errors.append("Parameter 'page' must be a positive integer")

    # Parse per_page
    per_page = default_per_page
    per_page_str = request.args.get("per_page", str(default_per_page))
    try:
        per_page = int(per_page_str)
        if per_page < 1:
            errors.append("Parameter 'per_page' must be a positive integer")
        elif per_page > max_per_page:
            errors.append(f"Parameter 'per_page' cannot exceed {max_per_page}")
    except ValueError:
        errors.append("Parameter 'per_page' must be a positive integer")

    # 1. Validation: check skill parameter
    if not skill or not skill.strip():
        errors.append("Parameter 'skill' is required and cannot be blank")

    # 2. Validation: parse start_time
    start_dt = None
    if not start_time_str:
        errors.append("Parameter 'start_time' is required")
    else:
        try:
            start_dt = parse_iso_datetime(start_time_str)
        except ValueError as e:
            errors.append(str(e))

    # 3. Validation: parse end_time
    end_dt = None
    if not end_time_str:
        errors.append("Parameter 'end_time' is required")
    else:
        try:
            end_dt = parse_iso_datetime(end_time_str)
        except ValueError as e:
            errors.append(str(e))

    # Return accumulated validation errors if any exist
    if errors:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "; ".join(errors)
            }
        }), 400

    # 4. Validation: logical ordering
    if start_dt >= end_dt:
        return jsonify({
            "error": {
                "code": "BAD_REQUEST",
                "message": "start_time must be chronologically before end_time"
            }
        }), 400

    # Query matching LSAs through the service layer (paginated at DB level)
    lsas, total = search_available_lsas(skill, start_dt, end_dt, page=page, per_page=per_page)

    import math
    total_pages = math.ceil(total / per_page) if per_page > 0 else 0

    # Format output according to standard API conventions
    data = [
        {
            "id": lsa.id,
            "name": lsa.name,
            "bio": lsa.bio,
            "hourly_rate": float(lsa.hourly_rate),
            "skills": [s.name for s in lsa.skills],
        }
        for lsa in lsas
    ]

    return jsonify({
        "data": data,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }
    }), 200
