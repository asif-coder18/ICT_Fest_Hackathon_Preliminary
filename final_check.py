import urllib.request, urllib.error, json, time

BASE = "http://localhost:8000"

def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=5)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

G = "\033[92m"
R = "\033[91m"
E = "\033[0m"

def check(label, ok, got=""):
    tag = f"{G}✓ PASS{E}" if ok else f"{R}✗ FAIL{E}"
    print(f"  {tag}  {label}" + (f"  → {got}" if not ok else ""))

# Multi-tenancy isolation
other_org = f"other-{int(time.time())}"
req("POST", "/auth/register", {"org_name": other_org, "username": "eve", "password": "evepass1"})
_, d2 = req("POST", "/auth/login", {"org_name": other_org, "username": "eve", "password": "evepass1"})
other_token = d2["access_token"]
s, rooms = req("GET", "/rooms", token=other_token)
check(f"Multi-tenancy: other org sees 0 rooms (got {len(rooms)})", len(rooms) == 0, rooms)

# Swagger UI
resp = urllib.request.urlopen(BASE + "/docs", timeout=5)
check(f"Swagger /docs → {resp.status}", resp.status == 200)

# OpenAPI schema
resp = urllib.request.urlopen(BASE + "/openapi.json", timeout=5)
schema = json.loads(resp.read())
paths = list(schema["paths"].keys())
check(f"OpenAPI schema has {len(paths)} routes", len(paths) > 0, paths)
print(f"\n  Registered routes:")
for p in sorted(paths):
    print(f"    {p}")
