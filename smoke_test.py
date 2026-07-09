"""Live smoke test — runs against the server on localhost:8000."""
import urllib.request
import urllib.error
import json
import time
import base64
from datetime import datetime, timezone, timedelta

BASE = "http://localhost:8000"

G  = "\033[92m"   # green
R  = "\033[91m"   # red
C  = "\033[96m"   # cyan
Y  = "\033[93m"   # yellow
E  = "\033[0m"

passed = 0
failed = 0


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def check(label, condition, got=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  {G}✓ PASS{E}  {label}")
    else:
        failed += 1
        print(f"  {R}✗ FAIL{E}  {label}  →  {got}")


def ft(h):
    return (datetime.now(timezone.utc) + timedelta(hours=h)).replace(
        minute=0, second=0, microsecond=0
    ).isoformat()


def section(title):
    print(f"\n{C}{'─'*60}{E}")
    print(f"{C}  {title}{E}")
    print(f"{C}{'─'*60}{E}")


org = f"live-{int(time.time())}"

# ── Health ────────────────────────────────────────────────────
section("Health")
s, d = req("GET", "/health")
check("/health → 200 {status: ok}", s == 200 and d == {"status": "ok"}, f"{s} {d}")

# ── Register ──────────────────────────────────────────────────
section("Auth — Register")
s, d = req("POST", "/auth/register", {"org_name": org, "username": "alice", "password": "secret12"})
check("First registration → 201, role=admin", s == 201 and d.get("role") == "admin", f"{s} {d}")

s, d = req("POST", "/auth/register", {"org_name": org, "username": "alice", "password": "wrongpa1"})
check("Duplicate username → 409", s == 409, f"{s} {d}")

s, d = req("POST", "/auth/register", {"org_name": org, "username": "ghost", "password": ""})
check("Empty password → 422", s == 422, f"{s} {d}")

s, d = req("POST", "/auth/register", {"org_name": org, "username": "bob", "password": "bobpass1"})
check("Second user in same org → role=member", s == 201 and d.get("role") == "member", f"{s} {d}")

# ── Login ─────────────────────────────────────────────────────
section("Auth — Login")
s, d = req("POST", "/auth/login", {"org_name": org, "username": "alice", "password": "secret12"})
check("Login → 200 with tokens", s == 200 and "access_token" in d and "refresh_token" in d, f"{s} {d}")
token = d["access_token"]
refresh_token = d["refresh_token"]

s, d = req("POST", "/auth/login", {"org_name": org, "username": "alice", "password": "WRONG"})
check("Wrong password → 401", s == 401, f"{s} {d}")

# ── JWT lifetime ──────────────────────────────────────────────
section("JWT — Token Lifetime")
parts = token.split(".")
pad = 4 - len(parts[1]) % 4
payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * pad))
lifetime_min = (payload["exp"] - payload["iat"]) / 60
check(f"Access token lifetime ~15 min (got {lifetime_min:.1f} min)", 14 <= lifetime_min <= 16, f"{lifetime_min:.1f} min")

# ── Refresh token ─────────────────────────────────────────────
section("Auth — Refresh Token")
s, d = req("POST", "/auth/refresh", {"refresh_token": refresh_token})
check("First refresh → 200", s == 200, f"{s} {d}")

s, d = req("POST", "/auth/refresh", {"refresh_token": refresh_token})
check("Second use of same refresh token → 401 (one-time use)", s == 401, f"{s} {d}")

# ── Logout / revocation ───────────────────────────────────────
section("Auth — Logout & Token Revocation")
s_logout, _ = req("POST", "/auth/logout", token=token)
check("Logout → 200", s_logout == 200, s_logout)

s, d = req("GET", "/rooms", token=token)
check("Revoked access token rejected → 401", s == 401, f"{s} {d}")

# Re-login for the rest of the tests
_, d = req("POST", "/auth/login", {"org_name": org, "username": "alice", "password": "secret12"})
token = d["access_token"]

# ── Rooms ─────────────────────────────────────────────────────
section("Rooms")
s, d = req("POST", "/rooms", {"name": "Focus Room", "capacity": 4, "hourly_rate_cents": 1500}, token)
check("Create room → 201", s == 201, f"{s} {d}")
room_id = d["id"]

s, d = req("POST", "/rooms", {"name": "Bad", "capacity": -1, "hourly_rate_cents": 0}, token)
check("Room with negative capacity/zero rate → 422", s == 422, f"{s} {d}")

s, d = req("GET", "/rooms", token=token)
check("List rooms returns at least 1", s == 200 and len(d) >= 1, f"{s} count={len(d)}")

# ── Bookings ──────────────────────────────────────────────────
section("Bookings — Create")
s, d = req("POST", "/bookings", {"room_id": room_id, "start_time": ft(50), "end_time": ft(52)}, token)
check("Create 2h booking → 201, price=3000 cents", s == 201 and d.get("price_cents") == 3000, f"{s} {d}")
booking_id = d.get("id")
ref_code = d.get("reference_code", "")
check(f"Reference code assigned ({ref_code})", ref_code.startswith("CW-"), ref_code)

t0 = ft(60)
s, d = req("POST", "/bookings", {"room_id": room_id, "start_time": t0, "end_time": t0}, token)
check("0-hour booking → 400", s == 400, f"{s} {d}")

# Back-to-back booking starts exactly when previous ends
s, d = req("POST", "/bookings", {"room_id": room_id, "start_time": ft(52), "end_time": ft(53)}, token)
check("Back-to-back booking → 201 (no false conflict)", s == 201, f"{s} {d}")
booking2_id = d.get("id")

# Genuine overlap
s, d = req("POST", "/bookings", {"room_id": room_id, "start_time": ft(51), "end_time": ft(53)}, token)
check("Overlapping booking → 409 ROOM_CONFLICT", s == 409 and d.get("code") == "ROOM_CONFLICT", f"{s} {d}")

# ── Pagination ────────────────────────────────────────────────
section("Bookings — Pagination")
s, d = req("GET", "/bookings?page=1&limit=10", token=token)
total = d.get("total", 0)
returned = len(d.get("items", []))
check(f"page=1 returns results (total={total}, returned={returned})", returned > 0, f"returned={returned}")
check("returned == total when total ≤ limit", returned == total, f"returned={returned} total={total}")

# ── Booking detail ────────────────────────────────────────────
section("Bookings — Detail")
s, d = req("GET", f"/bookings/{booking_id}", token=token)
check("GET /bookings/:id → 200", s == 200, f"{s}")
start_eq_created = d.get("start_time") == d.get("created_at")
check("start_time != created_at (Bug #9 fixed)", not start_eq_created,
      f"start_time={d.get('start_time')} created_at={d.get('created_at')}")

# ── Availability ──────────────────────────────────────────────
section("Rooms — Availability")
date = (datetime.now(timezone.utc) + timedelta(hours=50)).strftime("%Y-%m-%d")
s, d = req("GET", f"/rooms/{room_id}/availability?date={date}", token=token)
check(f"Availability for {date} → 200 with busy slots", s == 200 and len(d.get("busy", [])) > 0, f"{s} {d}")

# ── Stats ─────────────────────────────────────────────────────
section("Rooms — Stats")
s, d = req("GET", f"/rooms/{room_id}/stats", token=token)
check("Stats → 200, count ≥ 1", s == 200 and d.get("total_confirmed_bookings", 0) >= 1, f"{s} {d}")

# ── Cancel ────────────────────────────────────────────────────
section("Bookings — Cancel")
s, d = req("POST", f"/bookings/{booking_id}/cancel", token=token)
check("Cancel booking → 200", s == 200 and d.get("status") == "cancelled", f"{s} {d}")
check("refund_percent = 100 (>48h notice)", d.get("refund_percent") == 100, f"got {d.get('refund_percent')}")

s, d = req("POST", f"/bookings/{booking_id}/cancel", token=token)
check("Cancel already-cancelled → 409 ALREADY_CANCELLED", s == 409, f"{s} {d}")

# ── Multi-tenancy isolation ────────────────────────────────────
section("Multi-tenancy — Org Isolation")
other_org = f"other-{int(time.time())}"
s, d = req("POST", "/auth/register", {"org_name": other_org, "username": "eve", "password": "evepass1"})
_, d2 = req("POST", "/auth/login", {"org_name": other_org, "username": "eve", "password": "evepass1"})
other_token = d2["access_token"]
s, d = req("GET", "/rooms", token=other_token)
check("Other org cannot see alice's rooms", all(r["org_id"] != d.get("org_id") for r in d) or len(d) == 0,
      f"rooms returned: {d}")

# ── Swagger UI ────────────────────────────────────────────────
section("API Documentation")
try:
    resp = urllib.request.urlopen(BASE + "/docs")
    check("Swagger UI (/docs) → 200", resp.status == 200, resp.status)
except Exception as ex:
    check("Swagger UI (/docs) → 200", False, str(ex))

try:
    resp = urllib.request.urlopen(BASE + "/openapi.json")
    schema = json.loads(resp.read())
    check("OpenAPI schema has routes", len(schema.get("paths", {})) > 0, len(schema.get("paths", {})))
except Exception as ex:
    check("OpenAPI schema", False, str(ex))

# ── Summary ───────────────────────────────────────────────────
total_checks = passed + failed
print(f"\n{C}{'═'*60}{E}")
print(f"  {G}Passed: {passed}{E}  |  {R}Failed: {failed}{E}  |  Total: {total_checks}")
print(f"{C}{'═'*60}{E}\n")
