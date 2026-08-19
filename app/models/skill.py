from datetime import datetime, timezone
from app.extensions import db

# Junction table representing the many-to-many relationship between LSA profiles and Skills
lsa_skills = db.Table(
    "lsa_skills",
    db.Column(
        "lsa_id",
        db.Integer,
        db.ForeignKey("lsa_profiles.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    db.Column(
        "skill_id",
        db.Integer,
        db.ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
)

class Skill(db.Model):
    """Skill entity describing clinical, educational, or behavioral specializations."""
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Skill names are unique and indexed for efficient querying
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Skill id={self.id} name='{self.name}'>"
