# HabotConnect LSA Service Booking Backend

An LSA (Learning Support Assistant) Service Booking API developed with Python and Flask. This platform enables parents to request support sessions with specialized assistants, manages bookings to avoid overlapping allocations, and handles payment processing events via secure webhooks.

## Technology Stack
* **Python 3.10+**
* **Flask** (Web Framework with Application Factory pattern)
* **SQLAlchemy** (ORM)
* **Flask-Migrate / Alembic** (Database Migrations)
* **PostgreSQL 15** (Production Database — required)
* **Gunicorn** (Production WSGI Server)
* **Docker / Docker Compose** (Containerisation)
* **Flask-JWT-Extended** (JWT Authentication)
* **Flask-Limiter** (Rate Limiting)
* **Flasgger** (OpenAPI / Swagger Documentation)
* **Pytest** (Automated Testing)
* **GitHub Actions** (CI with PostgreSQL service)
* **python-dotenv** (Environment Configuration)

---

## Architectural Selection: Flask MVC vs. Django MVT

Flask with a layered MVC-style architecture was selected over Django MVT because this assessment requires a lightweight REST backend without a server-rendered template layer. SQLAlchemy provides ORM functionality and Flask blueprints/controllers provide the API layer.

### Rationale:
* **Django's MVT (Model-View-Template)** structure is optimized for monolithic, full-stack applications with built-in server-side HTML rendering. Since this project is a pure JSON REST API, Django's template engine is redundant.
* **Flask's MVC (Model-View-Controller)** style separation allows us to decouple:
  * **Models**: Domain entities (`app/models/`) managing schema representation.
  * **Controllers**: Blueprints (`app/routes/`) defining routing schemas and serialization.
  * **Service Layer**: Business Logic (`app/services/`) isolating operational algorithms, transactional gates, and external integrations from the web protocol layers.

---

## Key Features
* **Relational Database Design**: Normalized schema design mapping `Parent`, `LSAProfile`, `Skill`, `BookingRequest`, and `Payment` tables using SQLAlchemy and Alembic migrations.
* **LSA Search & Eager Loading**: Filters active LSAs by skill (case-insensitive) and timezone-aware schedule slots at the database level. Solves N+1 round-trips using SQLAlchemy `selectinload`.
* **Booking Availability & Concurrency**: Checks slot availability, computes pricing server-side using Decimal types, and serializes concurrent booking requests using pessimistic database row-locking (`WITH FOR UPDATE`) to prevent concurrent double-booking of LSAs.
* **Mock Payment Integration**: Handles HTTP payment charges via `requests` with a strict 5-second timeout and maps gateway/network failures to local payment and booking states.
* **HMAC-SHA256 Webhook Verification**: Secures asynchronous gateway callbacks against payload tampering using SHA256-HMAC headers, constant-time signature comparison, and database idempotency checks.
* **GitHub Actions CI Pipeline**: Validates repository updates against Python 3.10 with automated dependency caching.

---

## Domain Model & Database Schema

### Database Design & Canonical Choice
* **PostgreSQL** is selected as the canonical relational database for production deployments.
* **SQLite** is supported as a fallback for local development simplicity and isolated in-memory unit tests.

### Entities & Field Definitions
1. **Parent**: Represents the service clients. Attributes: `id`, `name`, `email` (unique, indexed), and standard timestamps.
2. **LSAProfile**: Represents the Learning Support Assistants. Attributes: `id`, `name`, `email` (unique, indexed), `bio`, `hourly_rate` (Decimal), `is_active` (boolean, indexed), and standard timestamps.
3. **Skill**: Represents specializations (e.g. ADHD Support, Autism Support). Attributes: `id`, `name` (unique, indexed), and `created_at`.
4. **BookingRequest**: Represents scheduled sessions. Attributes: `id`, `parent_id` (FK), `lsa_id` (FK), `start_time`, `end_time`, `status` (`PENDING`, `CONFIRMED`, `CANCELLED`, `FAILED`), `total_price` (Decimal), and standard timestamps.
5. **Payment**: Represents the financial record of a booking. Attributes: `id`, `booking_id` (FK, unique), `external_payment_id` (unique, indexed), `amount`, `currency` (default `'USD'`), `status` (`PENDING`, `SUCCESS`, `FAILED`), and standard timestamps.

### Database Relationships
* **Parent 1 ─── * BookingRequest**: One parent can place multiple booking requests.
* **LSAProfile 1 ─── * BookingRequest**: One LSA can be assigned to multiple booking requests.
* **LSAProfile * ─── * Skill**: Many-to-many relationship using a junction table (`lsa_skills`).
* **BookingRequest 1 ─── 1 Payment**: Modelled as a 1-to-1 relationship (`uselist=False`). This matches the assessment scope where a single booking tracks a single checkout session, simplifying webhook reconciliation and avoiding ledger complexities.

### Constraints & Indexes
* **Check Constraint**: `booking_requests.start_time < booking_requests.end_time` enforces date integrity at the database layer.
* **Composite Index**: `idx_bookings_lsa_overlap` on `booking_requests (lsa_id, status, start_time, end_time)` is created to support fast overlapping checks.
* **Normalization of Skills**: Specializations are normalized into their own table (`skills`) instead of comma-separated strings to allow fast searches, clean referential integrity, and indexing of individual skills.

---

## API Documentation: LSA Search Endpoint

### Endpoint Signature
* **URL**: `GET /api/v1/lsas/search`
* **Query Parameters**:
  * `skill` (string, required): Case-insensitive name of the required specialization (e.g. `Mathematics`).
  * `start_time` (string, required): ISO-8601 formatted, timezone-aware datetime representing session start (e.g. `2026-08-15T10:00:00Z`).
  * `end_time` (string, required): ISO-8601 formatted, timezone-aware datetime representing session end (e.g. `2026-08-15T11:00:00Z`).

### Example Request
```http
GET /api/v1/lsas/search?skill=Mathematics&start_time=2026-08-15T10:00:00Z&end_time=2026-08-15T11:00:00Z HTTP/1.1
Host: localhost:5000
Accept: application/json
```

### Example Response (200 OK)
```json
{
  "data": [
    {
      "id": 1,
      "name": "Alice LSA",
      "bio": "Certified behavior therapist specializing in early math education and ADHD support.",
      "hourly_rate": 35.0,
      "skills": [
        "Mathematics",
        "ADHD Support"
      ]
    }
  ]
}
```

### Validation & Error Behavior
The endpoint returns a `400 Bad Request` containing a standard JSON error message in the following scenarios:
* Missing parameters (`skill`, `start_time`, or `end_time`).
* Blank/whitespace-only `skill` value.
* Malformed datetime strings that do not comply with ISO-8601 formats.
* Logical date boundary mismatch where `start_time >= end_time`.

### Availability & Overlap Query Logic
Availability is filtered completely at the database layer (not in Python memory) using the following overlap rule:
$$\text{existing.start\_time} < \text{requested.end\_time} \quad \text{AND} \quad \text{existing.end\_time} > \text{requested.start\_time}$$
Active LSAs possessing the requested skill are excluded if they possess overlapping bookings in a `PENDING` or `CONFIRMED` state.

### N+1 Query Resolution
To avoid running an SQL select query to load associated skills for every matched LSA profile individually during serialization (resulting in $1 + N$ queries), the query is optimized using SQLAlchemy's `selectinload` strategy:
```python
available_lsas = (
    db.session.query(LSAProfile)
    .options(selectinload(LSAProfile.skills))
    ...
)
```
This forces SQLAlchemy to load associated skills for all matching LSAs in exactly **one secondary batch query** using an SQL `IN` filter, ensuring that the total database trips for any search execution is bounded at exactly **2 queries**, regardless of whether 2 or 10,000 LSAs are returned.

### Query-Count Verification
This performance boundary is enforced in `tests/test_search.py` via a custom `QueryCounter` that hooks into SQLAlchemy's `before_cursor_execute` event. The test verifies that running a search against 2 matching LSAs executes exactly 2 queries, and adding 5 more matching LSAs (total 7) still executes exactly 2 queries.

---

## API Documentation: Booking Creation Endpoint

### Endpoint Signature
* **URL**: `POST /api/v1/bookings/`
* **Request Payload**:
  * `parent_id` (integer, required): ID of the parent making the booking.
  * `lsa_id` (integer, required): ID of the LSA requested.
  * `start_time` (string, required): Timezone-aware ISO-8601 string.
  * `end_time` (string, required): Timezone-aware ISO-8601 string.

### Example Request
```http
POST /api/v1/bookings/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json

{
  "parent_id": 1,
  "lsa_id": 2,
  "start_time": "2026-08-15T10:00:00Z",
  "end_time": "2026-08-15T11:30:00Z"
}
```

### Example Response (201 Created)
```json
{
  "data": {
    "id": 42,
    "parent_id": 1,
    "lsa_id": 2,
    "start_time": "2026-08-15T10:00:00+00:00",
    "end_time": "2026-08-15T11:30:00+00:00",
    "status": "PENDING",
    "total_price": 75.0
  }
}
```

### Validation & Error Behavior
* Returns `400 Bad Request` if payload types are invalid, dates are malformed, or `start_time >= end_time`.
* Returns `404 Not Found` if the specified `parent_id` or `lsa_id` does not exist in the database.
* Returns `400 Bad Request` (with `LSA_INACTIVE` code) if the selected LSA is marked inactive.
* Returns `409 Conflict` (with `BOOKING_CONFLICT` code) if the LSA has overlapping active sessions.

### Booking Overlap & Blocking States
To prevent double bookings, the booking creation service queries the database for overlaps:
$$\text{existing.start\_time} < \text{requested.end\_time} \quad \text{AND} \quad \text{existing.end\_time} > \text{requested.start\_time}$$
* **Blocking Statuses**: Bookings with status `PENDING` or `CONFIRMED` block the requested slot.
* **Non-blocking Statuses**: Bookings in a `CANCELLED` or `FAILED` state do not conflict.

### Pricing Calculation
Monetary pricing is computed completely on the server-side to prevent client tampering.
$$\text{total\_price} = \text{lsa.hourly\_rate} \times \frac{\text{duration\_seconds}}{3600}$$
Monetary values are processed using Python's `Decimal` library to eliminate floating-point rounding errors and quantized to two decimal places (`Decimal('0.01')`).

### Concurrency & Transaction Strategy
To protect against race conditions where two parents attempt to book the same LSA for the same time slot concurrently, we implement a **pessimistic row-locking strategy**:
1. At the beginning of the transaction, the service queries the LSA profile utilizing database-level locking:
   ```python
   lsa = db.session.query(LSAProfile).filter_by(id=lsa_id).with_for_update().first()
   ```
2. In PostgreSQL, this locks the LSA row, forcing any concurrent transactions requesting the same `lsa_id` to block on their query.
3. The locked transaction checks for availability and inserts the booking safely.
4. When the transaction commits, the lock is released, and the blocked concurrent transaction proceeds, now seeing the newly inserted booking and correctly failing with a `409 Conflict`.
5. If any validation fails, the transaction is rolled back (`db.session.rollback()`), preserving data integrity.

---

## API Documentation: Payment Execution Endpoint

### Endpoint Signature
* **URL**: `POST /api/v1/bookings/<int:booking_id>/pay`
* **Path Parameters**:
  * `booking_id` (integer, required): The ID of the pending booking request.
* **Response Status**: `200 OK` (on gateway success or decline)

### Example Request
```http
POST /api/v1/bookings/42/pay HTTP/1.1
Host: localhost:5000
Content-Type: application/json
```

### Example Response (200 OK - Successful Payment)
```json
{
  "data": {
    "booking_id": 42,
    "payment_id": 12,
    "amount": 75.00,
    "currency": "USD",
    "status": "SUCCESS",
    "external_payment_id": "tx_success_42"
  }
}
```

### Exception & Failures Handling
* If the external gateway fails (returns HTTP 4xx/5xx, invalid JSON, or missing transaction keys), the payment endpoint returns a `502 Bad Gateway` status (code: `PAYMENT_GATEWAY_ERROR`).
* If the external gateway times out (timeout exceeded), returns `504 Gateway Timeout`.
* If a network connection error is encountered, returns `502 Bad Gateway`.

### Transaction Boundary & Consistency
To maintain consistency across system boundaries, we handle local database updates and external HTTP requests with care:
* **The Concurrency Isolation boundary**: We do NOT call the external HTTP payment service inside a database write transaction holding the LSA row lock. This prevents connection exhaustion (the HTTP call takes seconds while database threads wait).
* **Failure Reconciliation**: If the external HTTP gateway request fails or throws exceptions (timeouts, connection drops), the local transaction transitions both `Payment.status` and `BookingRequest.status` to `FAILED` and commits. This ensures that the local state matches the failed payment outcome and remains consistent across system boundaries.

---

## Continuous Integration (CI)

Our repository features a GitHub Actions workflow that executes the entire test suite on every push and pull request.

* **Pipeline File**: `.github/workflows/tests.yml`
* **Trigger Conditions**: Triggers on `push` and `pull_request` to `main` and `master` branches.
* **PostgreSQL Service**: CI spins up a real PostgreSQL 15 service container for all tests.
* **Migrations in CI**: `flask db upgrade` runs before pytest to ensure the schema is at head.
* **Concurrency Test**: The pessimistic row-locking concurrency test (previously skipped on SQLite) runs against PostgreSQL in CI, proving that double-booking protection works at the database level.

---

## Setup & Running Guide

### Prerequisites

Common:
- **Python 3.10+** (`python --version`)
- **pip** (comes with Python)
- **git**

For Docker path only:
- **Docker Desktop** or Docker Engine + Docker Compose

---

### Environment Configuration

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Generate secure random secrets (required for production):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> **Security note**: Never commit `.env`. It is in `.gitignore`. Production secrets must be set as environment variables — not hardcoded anywhere.

---

### Option A: Local Python Development (SQLite / local PostgreSQL)

#### 1. Create and activate a virtual environment

```bash
python -m venv venv

# Windows (PowerShell):
.\\venv\\Scripts\\Activate.ps1

# Linux/macOS:
source venv/bin/activate
```

#### 2. Install dependencies

```bash
pip install -r requirements.txt
```

#### 3. Configure environment

Edit `.env` for local development (SQLite is fine for development):

```env
FLASK_ENV=development
DATABASE_URL=sqlite:///dev.db     # or your local PostgreSQL URL
SECRET_KEY=any-local-dev-key
JWT_SECRET_KEY=any-local-jwt-key
WEBHOOK_SECRET=any-local-webhook-key
```

#### 4. Run database migrations

```bash
flask db upgrade
```

#### 5. (Optional) Seed development data

```bash
flask seed
```

#### 6. Start the development server

```bash
python run.py
```

The server runs on `http://localhost:5000`.

> **Note**: `python run.py` uses Flask's built-in development server. It is **not** suitable for production.

---

### Option B: Docker Compose — Production-like Environment

This runs the full stack: PostgreSQL 15 + Gunicorn + automatic migrations.

#### 1. Configure `.env`

```env
# Required secrets — generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=your-strong-secret-key-min-32-chars
JWT_SECRET_KEY=your-strong-jwt-key-min-32-chars
WEBHOOK_SECRET=your-strong-webhook-key-min-32-chars

# PostgreSQL credentials for the db service
POSTGRES_USER=habot
POSTGRES_PASSWORD=your-strong-postgres-password
POSTGRES_DB=habot_lsa_booking

FLASK_ENV=production
LOG_LEVEL=INFO
APP_PORT=5000
```

#### 2. Build the Docker image

```bash
docker compose build
```

#### 3. Start the stack

```bash
docker compose up
```

**What happens automatically:**
1. PostgreSQL 15 starts and becomes healthy (Docker health check with `pg_isready`).
2. The `web` container's entrypoint polls PostgreSQL until it accepts connections.
3. `flask db upgrade` runs once — applying all Alembic migrations.
4. Gunicorn starts with 3 worker processes.

#### 4. Verify the stack is running

```bash
# Liveness
curl http://localhost:5000/health

# Readiness (includes DB connectivity check)
curl http://localhost:5000/health/ready

# Swagger UI
open http://localhost:5000/apidocs/
```

#### 5. Stop the stack

```bash
docker compose down

# To also remove the database volume (destructive):
docker compose down -v
```

---

### API Endpoints Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Liveness probe |
| GET | `/health/ready` | None | Readiness probe (DB check) |
| GET | `/apidocs/` | None | Swagger UI |
| POST | `/api/v1/auth/register` | None | Register new parent |
| POST | `/api/v1/auth/login` | None | Login, receive JWT |
| GET | `/api/v1/auth/me` | JWT | Get authenticated parent |
| GET | `/api/v1/lsas/search` | None | Search available LSAs |
| POST | `/api/v1/bookings/` | JWT | Create a booking |
| POST | `/api/v1/bookings/<id>/pay` | JWT | Initiate payment |
| POST | `/api/payments/webhook/` | HMAC | Payment webhook callback |

---

### Health & Readiness Endpoints

**`GET /health`** — Liveness probe
- Returns `200 OK` if the Flask process is running.
- Does **not** check database connectivity.
- Use for container restart decisions (process crash detection).

**`GET /health/ready`** — Readiness probe
- Executes `SELECT 1` against the database.
- Returns `200 OK` with `{"status": "ready", "database": "connected"}` when ready.
- Returns `503 Service Unavailable` with `{"status": "not_ready", "database": "unavailable"}` when the database is unreachable.
- Use for load balancer routing and Docker healthchecks.

---

### Production WSGI Server — Gunicorn

The production container starts Gunicorn via `gunicorn.conf.py`:

| Setting | Default | Environment Override |
|---------|---------|---------------------|
| Bind address | `0.0.0.0:5000` | `GUNICORN_BIND` |
| Workers | `3` | `GUNICORN_WORKERS` |
| Threads per worker | `2` | `GUNICORN_THREADS` |
| Request timeout | `60s` | `GUNICORN_TIMEOUT` |
| Keepalive | `5s` | `GUNICORN_KEEPALIVE` |
| Access log | stdout | — |
| Error log | stderr | — |

**Worker sizing rationale**: The default of 3 workers is a safe baseline for typical container deployments with 1–2 vCPUs. The general heuristic for I/O-bound web applications is `2 * CPU_cores + 1`. Increase `GUNICORN_WORKERS` for higher-traffic deployments.

---

### Database Migrations

This project uses **Flask-Migrate / Alembic** as the schema source of truth. `db.create_all()` is **not** used in production.

```bash
# Apply all pending migrations
flask db upgrade

# Create a new migration after model changes
flask db migrate -m "describe your change"

# Downgrade one revision
flask db downgrade
```

In Docker, migrations run automatically via `entrypoint.sh` before Gunicorn starts.

---

### Running Tests

#### Local tests (SQLite in-memory — fast, no PostgreSQL required)

```bash
pytest tests/ -v
```

#### Tests against PostgreSQL (matches CI exactly)

```bash
TEST_DATABASE_URL="postgresql://user:pass@localhost:5432/habot_test" \
FLASK_ENV=testing \
SECRET_KEY=test-key \
JWT_SECRET_KEY=test-jwt-key \
WEBHOOK_SECRET=test-webhook-key \
python -m pytest tests/ -v
```

When `TEST_DATABASE_URL` points to PostgreSQL, the concurrency test (`test_concurrent_booking_attempts`) no longer skips — it exercises real PostgreSQL row-level locking.

---

### Security Configuration

| Concern | Implementation |
|---------|---------------|
| Authentication | JWT Bearer tokens via Flask-JWT-Extended |
| Password storage | bcrypt hashing — plaintext never stored or logged |
| Authorization | JWT-derived identity; resource ownership enforced on all mutating endpoints |
| IDOR protection | Booking ownership verified before payment initiation |
| Webhook authenticity | HMAC-SHA256 signature over `"{timestamp}.{body}"` |
| Webhook replay protection | `X-Webhook-Timestamp` header required within ±5 min tolerance |
| Rate limiting | 5 req/min on auth endpoints, 10/min on bookings, 60/min on search |
| Secrets in production | Validated at startup — placeholder values cause immediate startup failure |
| Debug mode | `DEBUG = False` enforced in `ProductionConfig` |
| Container user | Runs as non-root `appuser` in Docker |
| Error responses | Stack traces never returned to callers in production |

---

## Assessment Information
* **Candidate Name**: Shruti
* **Contact Email**: bshruti110@gmail.com
* **Hiring Position**: Python Backend Developer Assessment


### Endpoint Signature
* **URL**: `POST /api/payments/webhook/`
* **Request Payload**:
  * `booking_id` (integer, required): ID of the target booking.
  * `external_payment_id` (string, required): Gateway transaction ID hash.
  * `status` (string, required): Status of the payment event (`SUCCESS` or `FAILED`).
  * `amount` (decimal, required): The transaction billing total.
  * `currency` (string, required): Currency identifier (e.g. `USD`).

### Example Request (Payment Success)
```http
POST /api/payments/webhook/ HTTP/1.1
Host: localhost:5000
Content-Type: application/json

{
  "booking_id": 42,
  "external_payment_id": "tx_abc12345",
  "status": "SUCCESS",
  "amount": 75.00,
  "currency": "USD"
}
```

### Example Response (200 OK)
```json
{
  "status": "success",
  "message": "State transitioned successfully",
  "booking_id": 42,
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED"
}
```

### Webhook Signature Verification
To verify request authenticity and prevent spoofing or unauthorized state mutations, the webhook enforces HMAC-SHA256 signature verification:
* **Header**: The request must supply a `X-Webhook-Signature` header containing the hex digest of the raw request body hashed with the shared `WEBHOOK_SECRET`.
* **Formula**:
  $$\text{Signature} = \text{HMAC-SHA256}(\text{WEBHOOK\_SECRET}, \text{raw\_request\_body})$$
* **Mitigation**: Uses Python's `hmac.compare_digest()` to securely compare digests in constant time, preventing timing-attack vulnerabilities.
* **Response Codes**: Missing or mismatched signatures return `401 Unauthorized` immediately, bypassing parsing and database operations.

### Validation & Verification behavior
The webhook performs strict validations after signature verification:
* **Body Type**: Must be a valid JSON payload (returns `400 Bad Request` on parse failure).
* **Missing Fields**: All payload parameters are checked (returns `400 Bad Request` if missing).
* **Booking Lookup**: Returns `404 Not Found` if `booking_id` does not map to a database record.
* **Payment Integrity check**: Checks webhook `amount` against database values using Decimal precision, and checks webhook `currency` (case-insensitively). Returns `400 Bad Request` if mismatches are caught.
* **Status validation**: Status must be `SUCCESS` or `FAILED` (returns `400 Bad Request` on unsupported values).

### Idempotency Protection
* If the transaction has already reached a final status (`SUCCESS` or `FAILED`), duplicate events are recognized:
  - Updates are ignored.
  - Return code `200 OK` is returned with the message `"Webhook processed (idempotent duplicate)"`.
* This prevents duplicate processing, status corruption, or duplicate payment updates.

---

## Setup & Running Guide

### 1. Prerequisites
Ensure Python (3.10 or higher) is installed on your local environment.

### 2. Environment Configuration
Duplicate the `.env.example` file to create a `.env` configuration:
```bash
cp .env.example .env
```
Inside `.env`, configure your database URL, environment type, and secret keys. If no `DATABASE_URL` is supplied, the application automatically falls back to a local SQLite database (`sqlite:///dev.db`) to enable friction-free setup.

### 3. Install Dependencies
Create a Python virtual environment and install the required modules:
```bash
python -m venv venv
# On Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Run the Development Server
Execute the entry point module:
```bash
python run.py
```
The server will start on `http://localhost:5000`. You can test the operational health of the API at:
```bash
curl http://localhost:5000/health
```

### 5. Run Automated Tests
To run the pytest suite:
```bash
pytest
```

---

## Assessment Information
* **Candidate Name**: Shruti
* **Contact Email**: bshruti110@gmail.com
* **Hiring Position**: Python Backend Developer Assessment
