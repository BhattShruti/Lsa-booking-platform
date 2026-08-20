# LSA Booking Platform

A REST API for scheduling Learning Support Assistants (LSAs), managing bookings, and processing payment lifecycles. Built with Python and Flask, the service handles concurrent slot reservations via database row locking, integrates with external payment gateways, and processes status notifications through HMAC-verified webhooks.

## Highlights

- **Pessimistic Concurrency Control**: Uses PostgreSQL row-level locking (`WITH FOR UPDATE`) to prevent concurrent double-booking of assistants.
- **Payment Lifecycle & Reconciliation**: Manages multi-state payments (`PENDING`, `SUCCESS`, `FAILED`) with external HTTP gateway communication and asynchronous webhook processing.
- **HMAC-SHA256 Webhook Verification**: Secures incoming webhook callbacks with signature verification, timestamp-based replay protection, and idempotent event handling.
- **Efficient Relational Queries**: Uses SQLAlchemy `selectinload` to eliminate N+1 queries on assistant skill lookups, bounding search queries to 2 SQL executions regardless of result size.
- **JWT Authentication & Ownership Enforcement**: Enforces role-based data access and prevents IDOR vulnerabilities by deriving client identity strictly from authenticated JWT tokens.
- **Containerized Stack**: Includes multi-stage Docker builds running under a non-root user, Gunicorn WSGI configuration, and automatic database migration on startup.
- **PostgreSQL CI Pipeline**: GitHub Actions workflow running automated test suites against a real PostgreSQL 15 service container.

## Tech Stack

- **Backend**: Python 3.10+, Flask (Application Factory pattern)
- **Database**: PostgreSQL 15 (production), SQLite (local testing fallback), SQLAlchemy 2.0 ORM, Flask-Migrate / Alembic
- **Security**: Flask-JWT-Extended, Werkzeug security (`generate_password_hash` / `check_password_hash`), Flask-Limiter, HMAC-SHA256
- **Testing**: Pytest, Custom SQLAlchemy QueryCounter
- **Infrastructure**: Gunicorn, Docker & Docker Compose, GitHub Actions

## Architecture

The application follows a layered modular structure:

```text
app/
├── models/         # SQLAlchemy database models and constraints
├── routes/         # Flask blueprints, request validation, and HTTP responses
├── services/       # Core business logic, transaction management, and external integrations
├── schemas/        # Request and response data structures
├── utils/          # Authentication helpers, centralized error handlers, and logging
├── config.py       # Environment-specific configuration classes
└── extensions.py   # Initialized Flask extensions
```

- **Routes (`app/routes/`)**: Handle HTTP serialization, parse input parameters, enforce authentication/rate limits, and translate service errors into standard JSON error envelopes.
- **Services (`app/services/`)**: Contain domain logic, manage database transaction boundaries, enforce row locks, and orchestrate external network calls.
- **Models (`app/models/`)**: Define the relational schema, foreign keys, table indexes, check constraints, and relationships.

## Request Flow

```text
Client Request
      │
      ▼
Flask Route Blueprint
      │  (JWT Auth & Rate Limiting)
      ▼
Service Layer
      │  (Availability Validation & Row-Locking)
      ▼
PostgreSQL Transaction ──► Committed / Rolled back
      │
      ▼
Payment Gateway Integration (HTTP Call)
      │
      ▼
Webhook Callback ──► HMAC Verification ──► Idempotent State Reconciliation
```

## Key Engineering Decisions

### Concurrency-Safe Booking
To prevent race conditions where two parents attempt to book the same LSA for the same time slot simultaneously:
- When a booking is requested, the service queries the `LSAProfile` using `with_for_update()`, acquiring a pessimistic row-level lock in PostgreSQL.
- Overlap checks (`existing.start_time < requested.end_time AND existing.end_time > requested.start_time`) are executed while holding this lock.
- Conflicting transactions block until the holding transaction commits or rolls back, at which point the subsequent transaction reads the updated state and returns a `409 Conflict`.
- In CI, multi-threaded concurrency tests verify this behavior against a live PostgreSQL 15 database.

### Payment State Management
- External HTTP payment calls are executed **outside** the database row-locking transaction to avoid holding open database connections during network I/O.
- If the payment gateway succeeds or fails synchronously, the booking and payment records transition accordingly.
- If an HTTP timeout occurs, the payment is recorded with a `PENDING` state until the asynchronous webhook reconciles the final status.

### Webhook Security
Incoming payment webhook events (`POST /api/payments/webhook/`) enforce multi-layer verification:
- **HMAC-SHA256 Signature**: The gateway computes an HMAC-SHA256 digest over `{timestamp}.{raw_body}` using a shared secret. The endpoint verifies this signature using constant-time comparison (`hmac.compare_digest`).
- **Timestamp Replay Protection**: Requests require an `X-Webhook-Timestamp` header. Timestamps older than 300 seconds (or skewed into the future) are rejected with `401 Unauthorized`.
- **Idempotency**: Duplicate webhook events for payments already in a final state (`SUCCESS` or `FAILED`) return `200 OK` without re-processing or corrupting database records.

### Query Efficiency & Pagination
- **N+1 Prevention**: LSA search queries use SQLAlchemy's `selectinload(LSAProfile.skills)` strategy. The primary search and associated skill lookups execute in exactly 2 bounded SQL queries.
- **Database-Level Pagination**: Search results are paginated via SQL `LIMIT` and `OFFSET` subqueries with deterministic ordering (`hourly_rate ASC, id ASC`).

## API Endpoints

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| `GET` | `/health` | None | Liveness check (process up) |
| `GET` | `/health/ready` | None | Readiness check (database ping via `SELECT 1`) |
| `GET` | `/apidocs/` | None | Swagger UI interactive documentation |
| `POST` | `/api/v1/auth/register` | None | Register a parent account |
| `POST` | `/api/v1/auth/login` | None | Authenticate and obtain JWT token |
| `GET` | `/api/v1/auth/me` | JWT | Retrieve authenticated parent profile |
| `GET` | `/api/v1/lsas/search` | None | Search available LSAs by skill, time, and pagination |
| `POST` | `/api/v1/bookings/` | JWT | Create a new booking request |
| `POST` | `/api/v1/bookings/<id>/pay` | JWT | Initiate payment for an existing booking |
| `POST` | `/api/payments/webhook/` | HMAC | Gateway payment status webhook |

Full interactive API documentation and JSON schemas are available at `/apidocs/` via Swagger UI.

## Database Relationships

```text
Parent (1) ───────────< (N) BookingRequest (1) ─────────── (1) Payment
                                 │
                                 │ (N)
                                 ▼
                             LSAProfile (N) ───────────< (M) >─────────── (N) Skill
```

- **Parent to BookingRequest**: One-to-many relationship. Parent identity is linked to bookings for IDOR protection.
- **LSAProfile to BookingRequest**: One-to-many relationship.
- **BookingRequest to Payment**: One-to-one relationship (`uselist=False`).
- **LSAProfile to Skill**: Many-to-many relationship via `lsa_skills` association table.

## Security

- **Authentication**: JWT access tokens issued via Flask-JWT-Extended.
- **Password Hashing**: Passwords hashed using Werkzeug security (`generate_password_hash` / `check_password_hash`).
- **Authorization & IDOR Protection**: Mutating booking and payment endpoints verify that the requesting JWT subject matches the booking's `parent_id`.
- **Rate Limiting**: Configured per endpoint using Flask-Limiter (e.g., 5/min on auth, 10/min on bookings, 60/min on search).
- **Production Guardrails**: `ProductionConfig` validates environment variables on startup, rejecting empty/placeholder secrets, enforcing `DEBUG = False`, and requiring a valid PostgreSQL URL.

## Testing & CI

Automated tests cover model integrity, search filtering, concurrency locking, payment flows, webhook verification, and rate limiting.

- **Local Tests**: 132 passed, 1 skipped (SQLite does not support row-level locks, so the concurrency test skips when run against SQLite).
- **CI Tests (PostgreSQL 15)**: **133 passed, 0 skipped, 0 failed** in GitHub Actions.

Run the test suite locally:

```bash
python -m pytest tests/ -v
```

## Running Locally

### 1. Prerequisites
- Python 3.10+
- pip

### 2. Environment Setup

```bash
# Clone the repository
git clone https://github.com/BhattShruti/Lsa-booking-platform.git
cd Lsa-booking-platform

# Create and activate a virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

### 3. Run Migrations & Start Server

```bash
# Apply database migrations
flask db upgrade

# (Optional) Seed sample LSAs and skills
flask seed

# Start development server
python run.py
```

The server will be accessible at `http://localhost:5000`.

## Docker

Run the complete stack (PostgreSQL 15 + Gunicorn + automated migrations) using Docker Compose:

```bash
# Build images
docker compose build

# Start services in the background
docker compose up -d

# Verify readiness
curl http://localhost:5000/health/ready

# View logs
docker compose logs -f

# Tear down
docker compose down
```

## Continuous Integration

GitHub Actions workflow (`.github/workflows/tests.yml`) executes on every push and pull request:
1. Spawns a `postgres:15-alpine` service container with health checks.
2. Applies database migrations with `flask db upgrade`.
3. Runs pytest against PostgreSQL (`TEST_DATABASE_URL`), validating all unit, integration, and concurrency row-locking tests.
