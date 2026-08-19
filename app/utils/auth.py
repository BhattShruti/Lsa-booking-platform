from flask_jwt_extended import get_jwt_identity
from werkzeug.exceptions import Unauthorized, Forbidden
from app.extensions import db
from app.models.parent import Parent

def get_authenticated_parent() -> Parent:
    """
    Retrieve the Parent instance corresponding to the current JWT identity.
    Raises Unauthorized (401) if the identity is missing or doesn't match an existing Parent.
    """
    identity = get_jwt_identity()
    if not identity:
        raise Unauthorized("Missing or invalid authentication token.")

    try:
        parent_id = int(identity)
    except (ValueError, TypeError):
        raise Unauthorized("Invalid authentication token identity.")

    parent = db.session.get(Parent, parent_id)
    if not parent:
        raise Unauthorized("The authenticated parent user profile was not found.")

    return parent

def verify_booking_ownership(booking, parent: Parent) -> None:
    """
    Enforce resource ownership.
    Raises Forbidden (403) if the booking does not belong to the given parent.
    """
    if booking.parent_id != parent.id:
        raise Forbidden("Access to this booking resource is denied.")
