# CoWork API

> **Multi-tenant coworking space booking system** — REST API built with FastAPI, SQLAlchemy, and JWT authentication.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
  - [Docker (recommended)](#docker-recommended)
  - [Local (without Docker)](#local-without-docker)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
  - [Authentication](#authentication)
  - [Rooms](#rooms)
  - [Bookings](#bookings)
  - [Admin](#admin)
  - [Health](#health)
- [Business Rules](#business-rules)
- [Error Codes](#error-codes)
- [Data Models](#data-models)
- [Security](#security)
- [Running Tests](#running-tests)
- [Bug Report](#bug-report)

---

## Overview

CoWork is a production-ready REST API for managing bookable rooms across multiple isolated tenant organisations. Each organisation has its own rooms, admins, and members. Members book rooms for hourly time slots; admins manage rooms and pull usage reports.

**Key capabilities:**

- Multi-tenant isolation — organisations cannot see each other's data
- JWT authentication with access + refresh token rotation
- Conflict-free double-booking prevention
- Per-user booking quotas and rate limiting (concurrent-safe)
- Automatic refund calculation on cancellation
- CSV export and usage reports for administrators
- In-memory availability and report caching with targeted invalidation
- Root URL (`/`) auto-redirects to interactive Swagger UI docs

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                  FastAPI App                │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  /auth   │  │  /rooms  │  │/bookings │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│  ┌──────────┐  ┌──────────┐                 │
│  │  /admin  │  │ /health  │                 │
│  └──────────┘  └──────────┘                 │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │              Services               │    │
│  │  ratelimit · reference · stats      │    │
│  │  notifications · refunds · export   │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ┌──────────────┐   ┌────────────────────┐  │
│  │ SQLAlchemy   │   │   In-memory Cache  │  │
│  │ ORM + SQLite │   │ (availability,     │  │
│  └──────────────┘   │  usage reports)    │  │
│                     └────────────────────┘  │
└─────────────────────────────────────────────┘
```

Request flow: `HTTP Request → Router → Auth Dependency → Business Logic → SQLAlchemy → SQLite`

---

## Project Structure

```
ICT_Fest_Hackathon_Preliminary-main/
│
├── app/
│   ├── main.py              # App entry point, router registration, root redirect
│   ├── config.py            # Environment configuration (JWT_SECRET, DATABASE_URL)
│   ├── database.py          # SQLAlchemy engine + session factory
│   ├── models.py            # ORM models: Organization, User, Room, Booking, RefundLog
│   ├── schemas.py           # Pydantic request models with validation
│   ├── auth.py              # Password hashing, JWT creation/verification, dependencies
│   ├── cache.py             # In-memory caches for availability and reports
│   ├── errors.py            # AppError exception + JSON error handler
│   ├── serializers.py       # Booking response serializer
│   ├── timeutils.py         # ISO 8601 parsing + UTC rendering helpers
│   │
│   ├── routers/
│   │   ├── auth.py          # POST /auth/register|login|refresh|logout
│   │   ├── rooms.py         # GET|POST /rooms, availability, stats
│   │   ├── bookings.py      # GET|POST /bookings, GET|POST /bookings/{id}/cancel
│   │   ├── admin.py         # GET /admin/usage-report|export
│   │   └── health.py        # GET /health
│   │
│   └── services/
│       ├── ratelimit.py     # Rolling-window rate limiter (thread-safe)
│       ├── reference.py     # Unique booking reference code generator (thread-safe)
│       ├── stats.py         # Incremental per-room booking stats (thread-safe)
│       ├── notifications.py # Simulated email + audit log on booking events
│       ├── refunds.py       # Refund calculation and ledger entry
│       └── export.py        # CSV export generation
│
├── tests/
│   └── test_smoke.py        # Happy-path smoke test
│
├── run_bug_demo.py          # Live bug demonstration runner (all 19 bugs verified)
├── smoke_test.py            # Full live smoke test (30 checks)
├── Dockerfile               # Python 3.11-slim container
├── docker-compose.yml       # Single-service compose with persistent SQLite volume
└── requirements.txt         # Pinned Python dependencies
```

---

## Tech Stack

| Component | Library | Version |
|-----------|---------|---------|
| Web framework | FastAPI | 0.111.0 |
| ASGI server | Uvicorn | 0.30.1 |
| ORM | SQLAlchemy | 2.0.30 |
| Data validation | Pydantic v2 | 2.7.1 |
| JWT | PyJWT | 2.8.0 |
| Database | SQLite | (built-in) |
| Language | Python | 3.11+ |

---

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The API is available at **http://localhost:8000**  
Swagger UI docs open automatically at **http://localhost:8000/docs**

> The SQLite database is created automatically on first startup — no manual provisioning required.  
> Data persists in a named Docker volume (`cowork-data`).

### Local (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** — you will be redirected to the Swagger UI automatically.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET` | **Yes (production)** | `cowork-dev-secret-change-me` | HS256 signing secret. A startup warning is printed if not set. **Never use the default in production.** |
| `DATABASE_URL` | No | `sqlite:///./cowork.db` | SQLAlchemy database URL. SQLite is used by default. PostgreSQL is also supported. |

---

## API Reference

Interactive docs: **http://localhost:8000/docs** (Swagger UI) · **http://localhost:8000/redoc** (ReDoc)

### Authentication

All protected endpoints require `Authorization: Bearer <access_token>`.

| Method | Endpoint | Auth | Status | Description |
|--------|----------|------|--------|-------------|
| `POST` | `/auth/register` | No | 201 | Register. First user in org becomes `admin`, subsequent users become `member`. |
| `POST` | `/auth/login` | No | 200 | Returns `access_token` + `refresh_token`. |
| `POST` | `/auth/refresh` | No | 200 | Rotates both tokens. Refresh token is single-use. |
| `POST` | `/auth/logout` | Yes | 200 | Immediately invalidates the presented access token. |

**Register / Login request body:**
```json
{ "org_name": "acme-corp", "username": "alice", "password": "mypassword" }
```

**Login response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

**Token lifetime:**
- Access token: **15 minutes** (`exp − iat = 900s`)
- Refresh token: **7 days**

---

### Rooms

| Method | Endpoint | Auth | Status | Description |
|--------|----------|------|--------|-------------|
| `GET` | `/rooms` | Yes | 200 | List all rooms in caller's organisation. |
| `POST` | `/rooms` | Yes (admin) | 201 | Create a new room. |
| `GET` | `/rooms/{id}/availability` | Yes | 200 | Get confirmed busy intervals for a specific date. |
| `GET` | `/rooms/{id}/stats` | Yes | 200 | Live confirmed booking count and total revenue. |

**Create room body:**
```json
{ "name": "Focus Room", "capacity": 4, "hourly_rate_cents": 1500 }
```

**Availability query:** `GET /rooms/1/availability?date=2025-09-01`

**Availability response:**
```json
{
  "room_id": 1,
  "date": "2025-09-01",
  "busy": [
    { "start_time": "2025-09-01T09:00:00+00:00", "end_time": "2025-09-01T11:00:00+00:00" }
  ]
}
```

---

### Bookings

| Method | Endpoint | Auth | Status | Description |
|--------|----------|------|--------|-------------|
| `POST` | `/bookings` | Yes | 201 | Create a booking. |
| `GET` | `/bookings` | Yes | 200 | List caller's own bookings (paginated). |
| `GET` | `/bookings/{id}` | Yes | 200 | Get booking detail including refund history. |
| `POST` | `/bookings/{id}/cancel` | Yes | 200 | Cancel a booking and calculate refund. |

**Create booking body:**
```json
{
  "room_id": 1,
  "start_time": "2025-09-01T09:00:00+00:00",
  "end_time": "2025-09-01T11:00:00+00:00"
}
```

**Booking response:**
```json
{
  "id": 1,
  "reference_code": "CW-001000",
  "room_id": 1,
  "user_id": 2,
  "start_time": "2025-09-01T09:00:00+00:00",
  "end_time": "2025-09-01T11:00:00+00:00",
  "status": "confirmed",
  "price_cents": 3000,
  "created_at": "2025-08-15T10:00:00+00:00"
}
```

**List bookings:** `GET /bookings?page=1&limit=10`

```json
{
  "items": [ ... ],
  "page": 1,
  "limit": 10,
  "total": 42
}
```

**Cancel response:**
```json
{
  "id": 1,
  "status": "cancelled",
  "refund_percent": 100,
  "refund_amount_cents": 3000
}
```

---

### Admin

> Admin role required for all endpoints below.

| Method | Endpoint | Auth | Status | Description |
|--------|----------|------|--------|-------------|
| `GET` | `/admin/usage-report` | Yes (admin) | 200 | Per-room booking count and revenue for a date range. |
| `GET` | `/admin/export` | Yes (admin) | 200 | Download bookings as CSV. |

**Usage report:** `GET /admin/usage-report?from=2025-09-01&to=2025-09-30`

```json
{
  "from": "2025-09-01",
  "to": "2025-09-30",
  "rooms": [
    {
      "room_id": 1,
      "room_name": "Focus Room",
      "confirmed_bookings": 12,
      "revenue_cents": 36000
    }
  ]
}
```

**Export CSV:** `GET /admin/export?room_id=1&include_all=true`

CSV header: `id, reference_code, room_id, user_id, start_time, end_time, status, price_cents`

---

### Health

| Method | Endpoint | Auth | Status | Description |
|--------|----------|------|--------|-------------|
| `GET` | `/health` | No | 200 | Liveness probe. |

```json
{ "status": "ok" }
```

---

## Business Rules

1. **Datetime handling** — All input datetimes are ISO 8601. Timezone-aware inputs are converted to UTC before storage. Naive inputs are treated as UTC. All response datetimes include an explicit `+00:00` UTC offset.

2. **Booking duration** — Must be a whole number of hours, minimum 1 hour, maximum 8 hours. `end_time` must be strictly after `start_time`. `start_time` must be in the future.

3. **Pricing** — `price_cents = hourly_rate_cents × duration_hours`

4. **Conflict detection** — Two confirmed bookings conflict if `existing.start_time < new.end_time AND new.start_time < existing.end_time`. Back-to-back bookings are always allowed.

5. **Booking quota** — A member may hold at most **3 confirmed bookings** in the future. Violation → `409 QUOTA_EXCEEDED`.

6. **Rate limiting** — `POST /bookings` is limited to **20 requests per 60-second rolling window** per user. Excess → `429 RATE_LIMITED`.

7. **Cancellation refund tiers:**

   | Notice period | Refund |
   |---------------|--------|
   | ≥ 48 hours    | 100%   |
   | 24 – 48 hours | 50%    |
   | < 24 hours    | 0%     |

8. **Reference codes** — Every booking receives a unique `CW-XXXXXX` reference code, guaranteed unique under concurrent creation.

9. **Multi-tenancy** — Users (including admins) can only access data belonging to their own organisation. Cross-org resource IDs are treated as non-existent (`404`).

10. **Booking visibility** — Members can read and cancel only their own bookings. Admins can read and cancel any booking in their org.

11. **Refresh token rotation** — Each refresh token is single-use. Reuse returns `401`.

12. **Logout** — Immediately invalidates the presented access token for all subsequent requests.

---

## Error Codes

All errors return `{"detail": "<message>", "code": "<CODE>"}`.

| Code | HTTP | Trigger |
|------|------|---------|
| `INVALID_CREDENTIALS` | 401 | Wrong username or password |
| `UNAUTHORIZED` | 401 | Missing, expired, revoked, or wrong-type token |
| `FORBIDDEN` | 403 | Admin-only endpoint accessed by member |
| `ROOM_NOT_FOUND` | 404 | Room does not exist or belongs to another org |
| `BOOKING_NOT_FOUND` | 404 | Booking does not exist, belongs to another org, or member accessing another's booking |
| `USERNAME_TAKEN` | 409 | Username already registered in this organisation |
| `ROOM_CONFLICT` | 409 | Room already booked for the requested time slot |
| `QUOTA_EXCEEDED` | 409 | User has reached the 3 confirmed booking limit |
| `ALREADY_CANCELLED` | 409 | Booking is already in cancelled state |
| `RATE_LIMITED` | 429 | More than 20 booking creation requests in 60 seconds |
| `INVALID_BOOKING_WINDOW` | 400 | Past start time, non-whole/out-of-range duration, invalid date format |

Framework validation errors (missing fields, wrong types) return `422` with FastAPI's default shape.

---

## Data Models

### Organization
| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `name` | str | Unique, indexed |

### User
| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `org_id` | int | FK → Organization |
| `username` | str | Unique per org |
| `hashed_password` | str | PBKDF2-SHA256, 100k rounds |
| `role` | str | `admin` or `member` |
| `created_at` | datetime | UTC, naive storage |

### Room
| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `org_id` | int | FK → Organization |
| `name` | str | |
| `capacity` | int | ≥ 1 |
| `hourly_rate_cents` | int | ≥ 1 |

### Booking
| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `room_id` | int | FK → Room |
| `user_id` | int | FK → User |
| `start_time` | datetime | UTC, naive storage |
| `end_time` | datetime | UTC, naive storage |
| `status` | str | `confirmed` or `cancelled` |
| `reference_code` | str | Unique `CW-XXXXXX` |
| `price_cents` | int | |
| `created_at` | datetime | UTC, naive storage |

### RefundLog
| Field | Type | Notes |
|-------|------|-------|
| `id` | int | Primary key |
| `booking_id` | int | FK → Booking |
| `amount_cents` | int | |
| `status` | str | `processed` |
| `processed_at` | datetime | UTC, naive storage |

---

## Security

- **Passwords** — PBKDF2-SHA256 with 100,000 rounds and a random 16-byte salt. Constant-time comparison via `hmac.compare_digest`.
- **JWT** — HS256 signed. Claims include `sub`, `org`, `role`, `jti`, `iat`, `exp`, `type`. Token type checked on every request.
- **Token revocation** — Revoked JTIs stored in a thread-safe in-memory set. Revoked access tokens are rejected immediately.
- **Refresh token rotation** — Single-use enforcement via the same revocation set.
- **Multi-tenancy** — Every database query that touches rooms or bookings filters by `org_id`. Cross-org IDs return 404, not 403.
- **Input validation** — Pydantic v2 enforces field lengths and value ranges (e.g. `password min_length=8`, `capacity ge=1`).
- **Thread safety** — All shared in-memory state (revoked tokens, rate-limit buckets, reference counter, stats) is protected by `threading.Lock`.

> ⚠️ **Production note:** Set a strong `JWT_SECRET` environment variable before deploying. The default secret is publicly known.

---

## Running Tests

**Smoke test (pytest):**
```bash
pip install -r requirements.txt
pytest tests/
```

**Live bug demonstration** (requires running server):
```bash
# Start the server first
uvicorn app.main:app --port 8000

# Run the demo
python run_bug_demo.py
```

**Full live smoke test** (requires running server):
```bash
python smoke_test.py
```

---

## Bug Report

See [BUGS.md](BUGS.md) for the complete audit report of all 19 bugs found in the original codebase, their root causes, and the fixes applied.
