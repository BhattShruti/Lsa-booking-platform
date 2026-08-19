import pytest
from app import create_app
from app.extensions import db

@pytest.fixture
def app():
    """Create and configure a new Flask application instance for each test case."""
    # Use the isolated testing configuration
    app = create_app("testing")

    with app.app_context():
        # Prepare test database tables (empty for now)
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """A test client for the application to make HTTP requests."""
    return app.test_client()

@pytest.fixture
def get_auth_headers():
    """Fixture returning a function to generate JWT authorization headers."""
    from flask_jwt_extended import create_access_token
    def _headers(parent_id):
        token = create_access_token(identity=str(parent_id))
        return {"Authorization": f"Bearer {token}"}
    return _headers

