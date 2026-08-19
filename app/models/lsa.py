from datetime import datetime, timezone
from app.extensions import db
from app.models.skill import lsa_skills

class LSAProfile(db.Model):
    """LSAProfile entity representing the Learning Support Assistant."""
    __tablename__ = "lsa_profiles"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    # Unique email for communication and account lookup
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    bio = db.Column(db.Text, nullable=True)
    # Cost hourly rate for LSA session pricing
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)
    # Allows temporarily soft-disabling an assistant profile
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
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

    # Many-to-many relationship with Skill.
    # Exposing 'lsas' dynamically back on Skill.
    skills = db.relationship(
        "Skill",
        secondary=lsa_skills,
        backref=db.backref("lsas", lazy="select"),
    )

    # One-to-many relationship with BookingRequest
    bookings = db.relationship("BookingRequest", back_populates="lsa", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<LSAProfile id={self.id} name='{self.name}' rate={self.hourly_rate}>"
