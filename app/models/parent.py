from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db

class Parent(db.Model):
    """Parent entity representing the client utilizing the support services."""
    __tablename__ = "parents"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    # Unique, indexed email for authentication and record lookups
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    # Nullable password hash to safely handle legacy/non-migrated development records
    password_hash = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # One-to-many relationship with BookingRequest
    bookings = db.relationship("BookingRequest", back_populates="parent", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        """Hash and set the parent password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify the password against the stored hash. Returns False if password_hash is not set."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<Parent id={self.id} name='{self.name}' email='{self.email}'>"

