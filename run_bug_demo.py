"""
Bug Demonstration Script — CoWork API
======================================
Runs each confirmed bug and prints actual vs expected behavior.
No source code is modified.
"""

import sys
import os
import threading
import time
import inspect

# ── env must be set before any app import ─────────────────────────────────────
os.environ["JWT_SECRET"] = "cowork-dev-secret-change-me"
os.environ["DATABASE_URL"] = "sqlite:///./bug_demo_test.db"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Bootstrap the app (creates tables on the file-based DB)
from app.main import app  # noqa: E402  — side effect: creates tables
from app.database import SessionLocal  # noqa: E402
from app.models import Organization, User, Room, Booking  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)

# ── colour helpers ─────────────────────────────────────────────────────────────
PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
HEAD = "\033[96m"
END  = "\033[0m"

results: list[tuple] = []


def report(num: int, title: str, passed: bool, expected: str, actual: str):
    tag = "OK" if passed else "BUG CONFIRMED"
    status = PASS if passed else FAIL
    results.append((num, title, passed))
    print(f"\n{HEAD}{'─'*68}{END}")
    print(f"  Bug #{num:02d} | {title}")
    print(f"  Status   : {status} {tag}")
    print(f"  Expected : {expected}")
    print(f"  Actual   : {actual}")


# ── tiny helpers ───────────────────────────────────────────────────────────────
def _ts() -> str:
    return str(time.time()).replace(".", "")


def _register_and_login(org: str, username: str = "user", pw: str = "pw12345!"):
    client.post("/auth/register", json={"org_name": org, "username": username, "password": pw})
    r = client.post("/auth/login",    json={"org_name": org, "username": username, "password": pw})
    return r.json()["access_token"], {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_room(headers):
    r = client.post("/rooms", json={"name": "Room", "capacity": 4, "hourly_rate_cents": 1000}, headers=headers)
    return r.json()["id"]


def _future(h: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=h)).replace(
        minute=0, second=0, microsecond=0
    ).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# BUG #1 — JWT access token lifetime ×60 too long
# ══════════════════════════════════════════════════════════════════════════════
def bug01():
    import jwt as pyjwt
    from app.config import JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
    from app.auth import create_access_token

    db = SessionLocal()
    try:
        org = Organization(name=f"org1_{_ts()}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(org_id=org.id, username="u", hashed_password="x", role="member")
        db.add(user); db.commit(); db.refresh(user)
        token = create_access_token(user)
    finally:
        db.close()

    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    actual_min = (payload["exp"] - payload["iat"]) / 60
    passed = abs(actual_min - ACCESS_TOKEN_EXPIRE_MINUTES) < 2

    report(1, "JWT access token lifetime",
           passed,
           f"~{ACCESS_TOKEN_EXPIRE_MINUTES} minutes",
           f"{actual_min:.0f} minutes  ({actual_min / 60:.1f} hours!)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #2 — revocation checks sub instead of jti → revocation silently ignored
# ══════════════════════════════════════════════════════════════════════════════
def bug02():
    import jwt as pyjwt
    from app import auth as auth_mod
    from app.auth import create_access_token, revoke_access_token
    from app.config import JWT_SECRET, JWT_ALGORITHM
    from fastapi import Request

    auth_mod._revoked_tokens.clear()

    db = SessionLocal()
    try:
        org = Organization(name=f"org2_{_ts()}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(org_id=org.id, username="u", hashed_password="x", role="member")
        db.add(user); db.commit(); db.refresh(user)
        token = create_access_token(user)
    finally:
        db.close()

    payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    revoke_access_token(payload)  # adds payload["jti"] to _revoked_tokens

    # Now try to use the token — should be rejected
    scope = {
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    }
    request = Request(scope)
    try:
        from app.auth import get_token_payload
        get_token_payload(request)
        revoked = False
    except Exception:
        revoked = True

    report(2, "Token revocation (jti vs sub mismatch)",
           revoked,
           "Token rejected after revocation",
           "Token accepted after revocation — _revoked_tokens stores jti but check compares sub")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #3 — _revoked_tokens is a plain set (no lock)
# ══════════════════════════════════════════════════════════════════════════════
def bug03():
    from app import auth as auth_mod
    # FIX check: after the fix a separate _revoked_tokens_lock should exist
    has_lock = hasattr(auth_mod, "_revoked_tokens_lock")
    is_plain_unguarded = isinstance(auth_mod._revoked_tokens, set) and not has_lock
    report(3, "_revoked_tokens thread safety",
           not is_plain_unguarded,
           "Thread-safe container (Lock-protected)",
           "Plain set() — concurrent reads/writes will race" if is_plain_unguarded
           else f"Lock present: {has_lock}")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #5 — register returns existing user data (info leak + wrong status)
# ══════════════════════════════════════════════════════════════════════════════
def bug05():
    org = f"org5_{_ts()}"
    client.post("/auth/register", json={"org_name": org, "username": "alice", "password": "correct1"})
    r2 = client.post("/auth/register", json={"org_name": org, "username": "alice", "password": "wrongpa1"})
    leaked = r2.status_code == 201 and "user_id" in r2.json()

    report(5, "Register: existing username → info leak",
           not leaked,
           "409 Conflict",
           f"HTTP {r2.status_code} — returned {r2.json()} (existing user data exposed)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #6 — same refresh token accepted multiple times
# ══════════════════════════════════════════════════════════════════════════════
def bug06():
    org = f"org6_{_ts()}"
    client.post("/auth/register", json={"org_name": org, "username": "bob", "password": "pw12345!"})
    login = client.post("/auth/login", json={"org_name": org, "username": "bob", "password": "pw12345!"})
    rt = login.json()["refresh_token"]

    r1 = client.post("/auth/refresh", json={"refresh_token": rt})
    r2 = client.post("/auth/refresh", json={"refresh_token": rt})
    reused = r2.status_code == 200

    report(6, "Refresh token reuse (no one-time enforcement)",
           not reused,
           "401 on second use of same refresh token",
           f"HTTP {r2.status_code} — same token accepted again (infinite reuse possible)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #7 — page 1 shows 0 results (offset = page × limit instead of (page-1) × limit)
# ══════════════════════════════════════════════════════════════════════════════
def bug07():
    org = f"org7_{_ts()}"
    _, headers = _register_and_login(org)
    room_id = _make_room(headers)

    for i in range(3):
        client.post("/bookings", json={
            "room_id": room_id,
            "start_time": _future(500 + i * 2),
            "end_time":   _future(501 + i * 2),
        }, headers=headers)

    r = client.get("/bookings?page=1&limit=10", headers=headers)
    data = r.json()
    page1_count = len(data["items"])
    total = data["total"]
    passed = page1_count == total

    report(7, "Pagination: page=1 should return all items",
           passed,
           f"page=1 → {total} items",
           f"page=1 → {page1_count} items  (offset=1×10={10} applied, skipping everything)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #8 — limit param ignored, .limit(10) hardcoded in source
# ══════════════════════════════════════════════════════════════════════════════
def bug08():
    from app.routers import bookings as bmod
    src = inspect.getsource(bmod.list_bookings)
    hardcoded = ".limit(10)" in src and ".limit(limit)" not in src

    report(8, "list_bookings: limit param hardcoded",
           not hardcoded,
           ".limit(limit) respects query param",
           ".limit(10) is hardcoded — user-supplied limit is ignored")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #9 — get_booking returns created_at in start_time field
# ══════════════════════════════════════════════════════════════════════════════
def bug09():
    org = f"org9_{_ts()}"
    _, headers = _register_and_login(org)
    room_id = _make_room(headers)

    start = _future(600)
    b = client.post("/bookings", json={
        "room_id": room_id, "start_time": start, "end_time": _future(601)
    }, headers=headers)
    bid = b.json()["id"]
    created_at = b.json()["created_at"]

    detail = client.get(f"/bookings/{bid}", headers=headers).json()
    passed = detail["start_time"] != created_at

    report(9, "get_booking: start_time overwritten with created_at",
           passed,
           f"start_time ≈ {start[:16]}",
           f"start_time = {detail['start_time']}  (same as created_at={created_at})")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #11 — both refund tiers (24–48h and <24h) return 50% (dead code)
# ══════════════════════════════════════════════════════════════════════════════
def bug11():
    from app.routers import bookings as bmod
    src = inspect.getsource(bmod.cancel_booking)
    count_50 = src.count("refund_percent = 50")
    passed = count_50 < 2

    report(11, "Refund tiers: <24h branch dead code (always 50%)",
           passed,
           "Two distinct refund percentages for the two tiers",
           f"'refund_percent = 50' appears {count_50}× — elif and else are identical (one tier unreachable)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #12 — refund committed before booking status → split transaction
# ══════════════════════════════════════════════════════════════════════════════
def bug12():
    # Read the source file directly to avoid stale module cache.
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "app", "services", "refunds.py")
    with open(src_path) as f:
        lines = f.readlines()
    # Only count non-comment lines that contain db.commit()
    live_commits = [l.strip() for l in lines
                    if "db.commit()" in l and not l.strip().startswith("#")]
    refund_has_own_commit = len(live_commits) > 0
    report(12, "Cancel: split transaction (refund + status)",
           not refund_has_own_commit,
           "log_refund() does NOT commit — caller owns the single atomic commit",
           f"log_refund() commits separately: {live_commits}" if refund_has_own_commit
           else "log_refund() defers commit to caller — single atomic transaction")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #14 — conflict check is inclusive → back-to-back bookings blocked
# ══════════════════════════════════════════════════════════════════════════════
def bug14():
    org = f"org14_{_ts()}"
    _, headers = _register_and_login(org)
    room_id = _make_room(headers)

    b1 = client.post("/bookings", json={
        "room_id": room_id,
        "start_time": _future(700),
        "end_time":   _future(701),
    }, headers=headers)
    # Back-to-back: starts exactly when previous ends
    b2 = client.post("/bookings", json={
        "room_id": room_id,
        "start_time": _future(701),
        "end_time":   _future(702),
    }, headers=headers)
    passed = b2.status_code == 201

    report(14, "Conflict: inclusive boundary blocks back-to-back bookings",
           passed,
           "201 — adjacent booking is valid",
           f"HTTP {b2.status_code} — {b2.json()} (boundary touching incorrectly treated as overlap)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #15 — minimum duration (1h) not validated → 0-hour booking accepted
# ══════════════════════════════════════════════════════════════════════════════
def bug15():
    org = f"org15_{_ts()}"
    _, headers = _register_and_login(org)
    room_id = _make_room(headers)

    t = _future(800)
    b = client.post("/bookings", json={
        "room_id": room_id, "start_time": t, "end_time": t
    }, headers=headers)
    passed = b.status_code == 400

    report(15, "Min duration validation (< 1 hour accepted)",
           passed,
           "400 — zero-duration booking rejected",
           f"HTTP {b.status_code} — {b.json()}")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #17 — deadlock: notify_created and notify_cancelled acquire locks in reverse order
# ══════════════════════════════════════════════════════════════════════════════
def bug17():
    from app.services import notifications as nmod
    src_c = inspect.getsource(nmod.notify_created)
    src_x = inspect.getsource(nmod.notify_cancelled)

    email_first_in_created   = src_c.index("_email_lock") < src_c.index("_audit_lock")
    audit_first_in_cancelled = src_x.index("_audit_lock") < src_x.index("_email_lock")
    deadlock = email_first_in_created and audit_first_in_cancelled

    report(17, "Deadlock: lock acquisition order inversion in notifications",
           not deadlock,
           "Both functions acquire locks in the same order",
           "notify_created: email→audit | notify_cancelled: audit→email — classic ABBA deadlock")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #19 — reference code race: concurrent calls can get same counter value
# ══════════════════════════════════════════════════════════════════════════════
def bug19():
    from app.services import reference as refmod
    refmod._counter["value"] = 9000
    codes = []

    def gen():
        codes.append(refmod.next_reference_code())

    threads = [threading.Thread(target=gen) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()

    dupes = len(codes) != len(set(codes))
    report(19, "Reference code race condition (duplicate codes)",
           not dupes,
           "All 6 codes unique",
           f"{codes}  →  duplicates={'YES ← race confirmed' if dupes else 'no this run (race is non-deterministic — exists in code)'}")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #20 — stats lost updates under concurrency
# ══════════════════════════════════════════════════════════════════════════════
def bug20():
    from app.services import stats as smod
    room_id = 88888
    smod._stats.pop(room_id, None)
    n = 6

    def inc():
        smod.record_create(room_id, 1000)

    threads = [threading.Thread(target=inc) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()

    actual = smod.get(room_id)["count"]
    passed = actual == n
    report(20, "Stats lost-update race condition",
           passed,
           f"count = {n}",
           f"count = {actual}  ({'LOST UPDATES ← race confirmed' if actual < n else 'ok this run — race exists in code'})")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #22 — export fetch_bookings_raw has no org_id scope
# ══════════════════════════════════════════════════════════════════════════════
def bug22():
    from app.services.export import fetch_bookings_raw
    src = inspect.getsource(fetch_bookings_raw)
    has_scope = "org_id" in src

    report(22, "Export: fetch_bookings_raw missing org_id scope",
           has_scope,
           "Query filtered by org_id",
           "No org_id filter — admin can export any org's bookings (multi-tenancy breach)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #24 — parse_input_datetime strips tz without converting to UTC first
# ══════════════════════════════════════════════════════════════════════════════
def bug24():
    from app.timeutils import parse_input_datetime
    # 14:00 IST (+05:30) = 08:30 UTC
    result = parse_input_datetime("2025-09-01T14:00:00+05:30")
    passed = result.hour == 8

    report(24, "parse_input_datetime: non-UTC offset stored wrong",
           passed,
           "Stored hour = 8  (14:00 IST → 08:30 UTC)",
           f"Stored hour = {result.hour}  (offset stripped without conversion — wrong time stored)")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #28 — empty password accepted (no min-length validation)
# ══════════════════════════════════════════════════════════════════════════════
def bug28():
    org = f"org28_{_ts()}"
    r = client.post("/auth/register", json={"org_name": org, "username": "ghost", "password": ""})
    passed = r.status_code == 422

    report(28, "RegisterRequest: empty password not rejected",
           passed,
           "422 Unprocessable Entity",
           f"HTTP {r.status_code} — empty password accepted silently")


# ══════════════════════════════════════════════════════════════════════════════
# BUG #29 — room with negative capacity / zero rate accepted
# ══════════════════════════════════════════════════════════════════════════════
def bug29():
    org = f"org29_{_ts()}"
    _, headers = _register_and_login(org)
    r = client.post("/rooms", json={"name": "Bad", "capacity": -1, "hourly_rate_cents": 0}, headers=headers)
    passed = r.status_code == 422

    report(29, "RoomCreateRequest: negative/zero values not rejected",
           passed,
           "422 Unprocessable Entity",
           f"HTTP {r.status_code} — {r.json()}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print(f"\n{HEAD}{'═'*68}")
    print("  CoWork API — Bug Demonstration Runner")
    print(f"{'═'*68}{END}")

    bug01()
    bug02()
    bug03()
    bug05()
    bug06()
    bug07()
    bug08()
    bug09()
    bug11()
    bug12()
    bug14()
    bug15()
    bug17()
    bug19()
    bug20()
    bug22()
    bug24()
    bug28()
    bug29()

    confirmed = [r for r in results if not r[2]]
    ok        = [r for r in results if r[2]]

    print(f"\n{HEAD}{'═'*68}")
    print(f"  SUMMARY  |  Tested: {len(results)}  |  "
          f"\033[91mBugs Confirmed: {len(confirmed)}\033[0m  |  "
          f"\033[92mPassed/OK: {len(ok)}\033[0m")
    print(f"{'═'*68}{END}")

    if confirmed:
        print(f"\n{HEAD}  ✗ Confirmed Bugs:{END}")
        for num, title, _ in confirmed:
            print(f"    \033[91m#{num:02d}\033[0m  {title}")

    if ok:
        print(f"\n{HEAD}  ✓ Passed (or race non-deterministic):{END}")
        for num, title, _ in ok:
            print(f"    \033[92m#{num:02d}\033[0m  {title}")

    print()

    # cleanup test db
    try:
        os.remove(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bug_demo_test.db"))
    except Exception:
        pass
