from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models.lsa import LSAProfile
from app.models.skill import Skill
from app.models.booking import BookingRequest

def search_available_lsas(
    skill_name: str,
    start_time: datetime,
    end_time: datetime,
    page: int = 1,
    per_page: int = 10,
) -> tuple[list[LSAProfile], int]:
    """
    Search for available, active LSAs possessing the specified skill (case-insensitive)
    within the requested time frame.

    Query logic:
    - LSA profile must be active (is_active = True).
    - LSA profile must possess the requested skill (case-insensitive matching on Skill.name).
    - LSA profile must NOT have any conflicting/overlapping bookings (PENDING or CONFIRMED status)
      during the requested period.

    Pagination:
    - Performed at the database level using LIMIT/OFFSET.
    - Stable ORDER BY LSAProfile.id ASC ensures consistent, deterministic pages.

    Resolves N+1 query problem by using selectinload to fetch associated Skills for all matched
    LSAs in a single secondary batch query instead of a query per row during serialization.

    Returns:
        (lsas, total): List of LSAProfile objects for the current page, and integer total count.
    """
    # Define subquery to fetch LSA IDs that have overlapping bookings during the requested window.
    # Standard overlap rule: existing_start < requested_end AND existing_end > requested_start
    overlapping_lsa_ids = (
        db.session.query(BookingRequest.lsa_id)
        .filter(
            BookingRequest.status.in_(["PENDING", "CONFIRMED"]),
            BookingRequest.start_time < end_time,
            BookingRequest.end_time > start_time,
        )
    )

    # Build the set of qualifying LSA IDs using a subquery.
    # Joining LSAProfile.skills can produce duplicate LSAProfile rows if an LSA has multiple
    # matching skills; using a subquery to pre-filter IDs avoids that duplication cleanly
    # without relying on DISTINCT ON (which is PostgreSQL-only).
    qualifying_lsa_ids_subquery = (
        db.session.query(LSAProfile.id)
        .join(LSAProfile.skills)
        .filter(
            LSAProfile.is_active == True,
            func.lower(Skill.name) == skill_name.lower(),
            ~LSAProfile.id.in_(overlapping_lsa_ids),
        )
        .subquery()
    )

    # Count total matching records (without pagination)
    total = (
        db.session.query(func.count())
        .select_from(qualifying_lsa_ids_subquery)
        .scalar()
    ) or 0

    from sqlalchemy import select
    # Paginated query with stable ORDER BY and eager skill loading
    offset = (page - 1) * per_page
    available_lsas = (
        db.session.query(LSAProfile)
        .options(selectinload(LSAProfile.skills))  # Eager load skills relationship
        .filter(LSAProfile.id.in_(select(qualifying_lsa_ids_subquery.c.id)))
        .order_by(LSAProfile.id.asc())             # Stable, deterministic ordering
        .limit(per_page)
        .offset(offset)
        .all()
    )

    return available_lsas, total
