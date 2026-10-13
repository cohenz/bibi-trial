"""Operator client for the production admin API (signed calls), for working sessions.

The secret is never stored in the repo: set NTK_OPS_SECRET, or NTK_OPS_SECRET_FILE pointing to a file that holds it.
Key id / actor default to the "claude-ops" key (NTK_SERVICE_KEYS_EXTRA on the api service; scopes admin:read,
admin:ingest, admin:publish). A new session that does not have the secret needs a new key, created with the user's
approval and entered directly in Railway (never pasted in chat).

    python tools/ops.py call GET /v2/admin/batches
    python tools/ops.py call POST /v2/admin/digests/batch '{"limit": 100, "now": true}'
    python tools/ops.py status        # inbox, jobs, batches, allowance, hearings with digests
    python tools/ops.py stuck         # rerun jobs 'running' with no progress for 16+ minutes (force_stale)
    python tools/ops.py failed        # rerun failed jobs from the stage that failed
"""

from __future__ import annotations

import collections
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import requests

BASE = os.environ.get("NTK_API", "https://api-production-6562.up.railway.app")
KEY_ID = os.environ.get("NTK_OPS_KEY_ID", "claude-ops-2")
ACTOR = os.environ.get("NTK_OPS_ACTOR", "claude-session")


def _secret() -> str:
    if os.environ.get("NTK_OPS_SECRET"):
        return os.environ["NTK_OPS_SECRET"].strip()
    f = os.environ.get("NTK_OPS_SECRET_FILE")
    if f and Path(f).exists():
        return Path(f).read_text().strip()
    sys.exit("set NTK_OPS_SECRET or NTK_OPS_SECRET_FILE (never commit the secret)")


def call(method: str, path: str, body=None, query: str = "", timeout: int = 120):
    ts, nonce = str(int(time.time())), secrets.token_hex(12)
    raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
    q = urlencode(sorted(parse_qsl(query, keep_blank_values=True)))
    canonical = "\n".join([method, path, q, ts, nonce, ACTOR, hashlib.sha256(raw).hexdigest()])
    sig = hmac.new(_secret().encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers = {"X-NTK-Key-Id": KEY_ID, "X-NTK-Timestamp": ts, "X-NTK-Nonce": nonce, "X-NTK-Actor": ACTOR,
               "X-NTK-Signature": sig, "Content-Type": "application/json"}
    r = requests.request(method, BASE + path + ("?" + query if query else ""), data=raw or None, headers=headers,
                         timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:500]


def status() -> None:
    _, inbox = call("GET", "/v2/admin/inbox", query="limit=1")
    print("inbox:", inbox["summary"]["totals"], inbox["summary"]["by_status"])
    for s in ("queued", "running", "failed"):
        _, d = call("GET", "/v2/admin/ingestion-jobs", query=f"limit=200&status={s}")
        print(f"jobs {s}:", len(d.get("items", [])))
    _, b = call("GET", "/v2/admin/batches", query="limit=20")
    al = b.get("allowance") or {}
    print("allowance:", {k: al.get(k) for k in ("remaining", "approved_total", "updated_at")},
          (al.get("last_error") or "")[:80])
    for x in b["items"][:8]:
        built = collections.Counter((y.get("via"), y.get("state"), "err" if y.get("error") else "")
                                    for y in (x.get("result") or {}).get("built", []))
        print(" ", x["name"][-10:], x["created_at"][:16], x["state"], x["items"], dict(built))
    h = requests.get(BASE + "/v2/hearings", params={"limit": 500}, timeout=60).json().get("items", [])
    print("hearings:", len(h), "with digest:", sum(1 for x in h if x.get("has_digest")))


def stuck(minutes: int = 16) -> None:
    _, d = call("GET", "/v2/admin/ingestion-jobs", query="limit=200&status=running")
    now = dt.datetime.now(dt.UTC)
    for j in d.get("items", []):
        idle = (now - dt.datetime.fromisoformat(j["updated_at"])).total_seconds() / 60
        print(j["id"], j["stage"], int(idle), "min idle")
        if idle >= minutes:
            st, _ = call("POST", f"/v2/admin/ingestion-jobs/{j['id']}/rerun", {"stages": [j["stage"]], "force_stale": True})
            print("  rerun", st)


def failed() -> None:
    _, d = call("GET", "/v2/admin/ingestion-jobs", query="limit=200&status=failed")
    for j in d.get("items", []):
        stage = (j.get("error") or {}).get("stage") if isinstance(j.get("error"), dict) else None
        stage = stage or j.get("stage")
        if stage == "publish":
            print(j["id"], "failed at publish: publish it from the review screen instead")
            continue
        st, _ = call("POST", f"/v2/admin/ingestion-jobs/{j['id']}/rerun", {"stages": [stage]})
        print(j["id"], stage, "rerun", st)  # later stages are still pending and run after it


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "call":
        m, p = sys.argv[2], sys.argv[3]
        b = json.loads(sys.argv[4]) if len(sys.argv) > 4 and sys.argv[4] else None
        q = sys.argv[5] if len(sys.argv) > 5 else ""
        code, out = call(m, p, b, q)
        print(code, json.dumps(out, ensure_ascii=False, indent=1, default=str)[:8000])
    else:
        {"status": status, "stuck": stuck, "failed": failed}[cmd]()
