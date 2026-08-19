"""
OpenAPI / Swagger UI Tests
==========================
Verify that the interactive API documentation endpoint is reachable and returns
valid Swagger JSON.
"""
import pytest


def test_swagger_ui_reachable(client):
    """Verify GET /apidocs/ returns 200 OK (Swagger UI is mounted and served)."""
    response = client.get("/apidocs/")
    assert response.status_code == 200


def test_swagger_spec_reachable(client):
    """Verify the raw Swagger JSON spec endpoint returns 200 and parses as valid JSON."""
    response = client.get("/apispec_1.json")
    assert response.status_code == 200
    spec = response.get_json()
    assert spec is not None


def test_swagger_spec_contains_info(client):
    """Verify the Swagger spec contains an 'info' block with a title."""
    response = client.get("/apispec_1.json")
    spec = response.get_json()
    assert "info" in spec
    assert "title" in spec["info"]


def test_swagger_spec_documents_auth_endpoints(client):
    """Verify the Swagger spec documents the authentication endpoints."""
    response = client.get("/apispec_1.json")
    spec = response.get_json()
    # Flasgger may use 'paths' (OpenAPI 3) or 'paths' (Swagger 2)
    paths = spec.get("paths", {})
    assert any("register" in path for path in paths), "Expected /register in Swagger paths"
    assert any("login" in path for path in paths), "Expected /login in Swagger paths"
    assert any("/me" in path for path in paths), "Expected /me in Swagger paths"


def test_swagger_spec_documents_lsa_search(client):
    """Verify the Swagger spec documents the LSA search endpoint."""
    response = client.get("/apispec_1.json")
    spec = response.get_json()
    paths = spec.get("paths", {})
    assert any("search" in path for path in paths), "Expected /search in Swagger paths"


def test_swagger_spec_documents_bookings(client):
    """Verify the Swagger spec documents booking endpoints."""
    response = client.get("/apispec_1.json")
    spec = response.get_json()
    paths = spec.get("paths", {})
    assert any("booking" in path for path in paths), "Expected booking paths in Swagger spec"


def test_swagger_spec_documents_webhook(client):
    """Verify the Swagger spec documents the webhook endpoint."""
    response = client.get("/apispec_1.json")
    spec = response.get_json()
    paths = spec.get("paths", {})
    assert any("webhook" in path for path in paths), "Expected webhook in Swagger paths"
