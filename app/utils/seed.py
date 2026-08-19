from decimal import Decimal
from app.extensions import db
from app.models.parent import Parent
from app.models.lsa import LSAProfile
from app.models.skill import Skill

def seed_db() -> None:
    """Seed the database with initial Parents, LSAs, and Skills for local testing."""
    # Check if database is already populated
    if Parent.query.first() or LSAProfile.query.first() or Skill.query.first():
        return

    # 1. Create Skills
    skills_map = {
        "Mathematics": Skill(name="Mathematics"),
        "ADHD Support": Skill(name="ADHD Support"),
        "Autism Support": Skill(name="Autism Support"),
        "English": Skill(name="English"),
    }
    db.session.add_all(skills_map.values())
    db.session.flush()  # Generate primary keys in session

    # 2. Create Parents
    parents = [
        Parent(name="John Doe", email="john.doe@example.com"),
        Parent(name="Jane Smith", email="jane.smith@example.com"),
    ]
    db.session.add_all(parents)

    # 3. Create LSAs and map their skills
    lsa1 = LSAProfile(
        name="Alice Johnson",
        email="alice.johnson@example.com",
        bio="Certified behavior therapist specializing in early math education and ADHD support.",
        hourly_rate=Decimal("35.00"),
        is_active=True,
    )
    lsa1.skills.extend([skills_map["Mathematics"], skills_map["ADHD Support"]])

    lsa2 = LSAProfile(
        name="Bob Miller",
        email="bob.miller@example.com",
        bio="Specialist support assistant focused on autism spectrum support.",
        hourly_rate=Decimal("40.00"),
        is_active=True,
    )
    lsa2.skills.append(skills_map["Autism Support"])

    lsa3 = LSAProfile(
        name="Charlie Davis",
        email="charlie.davis@example.com",
        bio="Experienced reading tutor specializing in Dyslexia and general English support.",
        hourly_rate=Decimal("30.00"),
        is_active=True,
    )
    lsa3.skills.append(skills_map["English"])

    db.session.add_all([lsa1, lsa2, lsa3])
    db.session.commit()
