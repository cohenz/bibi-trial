"""Live end-to-end check against running services (API + worker + Redis +
S3-compatible storage). Mirrors what the WordPress plugin does:

  presign → browser-style PUT to the presigned URL → create ingestion job →
  poll job → list review tasks → approve → publish → public reads → ask

Usage:
  NTK_E2E_API=http://localhost:8000 NTK_E2E_KEY_ID=wp-dev NTK_E2E_SECRET=... \
  python tools/e2e_live.py tests/fixtures/synthetic_protocol.pdf
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from ntk_api.security import sign  # noqa: E402

API = os.environ.get("NTK_E2E_API", "http://localhost:8000")
KEY = os.environ.get("NTK_E2E_KEY_ID", "wp-dev")
SECRET = os.environ["NTK_E2E_SECRET"]
S = requests.Session()
S.trust_env = False


def call(method: str, path: str, body=None, *, admin: bool = True):
    raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b""
    headers = {"Content-Type": "application/json"}
    if admin:
        ts, nonce = str(int(time.time())), secrets.token_hex(12)
        p, _, q = path.partition("?")
        headers.update({"X-NTK-Key-Id": KEY, "X-NTK-Timestamp": ts, "X-NTK-Nonce": nonce, "X-NTK-Actor": "e2e-live",
                        "X-NTK-Signature": sign(SECRET, method, p, q, ts, nonce, "e2e-live", raw)})
    r = S.request(method, API + path, data=raw if body is not None else None, headers=headers, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    return r.status_code, data


def step(name: str, ok: bool, detail="") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        sys.exit(1)


def main(pdf_path: str) -> None:
    data = Path(pdf_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    st, ready = call("GET", "/v2/ready", admin=False)
    step("ready", st == 200, json.dumps(ready))
    st, up = call("POST", "/v2/admin/uploads/presign", {"filename": Path(pdf_path).name, "mime_type": "application/pdf",
                                                        "size_bytes": len(data), "sha256": sha})
    step("presign", st == 200, up.get("key", up))
    if not up["already_exists"]:
        r = S.request(up["method"], up["url"], data=data, headers=up["headers"], timeout=60)
        step("direct PUT to storage (presigned)", 200 <= r.status_code < 300, f"HTTP {r.status_code}")
    st, job = call("POST", "/v2/admin/ingestion-jobs", {"upload_id": up["upload_id"],
                   "document": {"title": "SYNTHETIC live e2e", "hearing_date": "2021-04-12", "court_record_status": "filed"}})
    step("create job", st == 202, job)
    jid = job["job_id"]
    for _ in range(120):
        st, j = call("GET", f"/v2/admin/ingestion-jobs/{jid}")
        if j.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(1)
    step("job finished via worker", j.get("status") == "succeeded",
         " ".join(f"{s['stage']}:{s['status']}" for s in j.get("stages", [])))
    st, tasks = call("GET", "/v2/admin/review-tasks")
    arts = [t for t in tasks["items"] if t["object_type"] == "artifact"]
    step("review tasks opened", bool(arts), f"{len(tasks['items'])} open")
    for t in arts:
        st, r = call("POST", f"/v2/admin/artifacts/{t['object_id']}/review", {"decision": "approve", "notes": "live e2e"})
        step("approve", st == 200, r)
        st, r = call("POST", f"/v2/admin/artifacts/{t['object_id']}/publish", {"include_sources": True})
        step("publish", st == 200, r.get("corpus_version", r))
    st, hs = call("GET", "/v2/hearings", admin=False)
    step("public hearings", st == 200 and hs["items"], len(hs["items"]))
    st, h = call("GET", f"/v2/hearings/{hs['items'][0]['id']}", admin=False)
    step("public hearing digest", st == 200 and h["digest"] is not None)
    cit = h["digest"]["citations"][0]
    st, c = call("GET", f"/v2/citations/{cit['source_unit_id']}", admin=False)
    step("citation permalink", st == 200 and c["citation"]["page"] == cit["page"], f"p{cit['page']} l{cit['line_start']}-{cit['line_end']}")
    st, a = call("POST", "/v2/ask", {"question": "מי שלח את המיילים?"}, admin=False)
    step("ask", st == 200 and a["citations"], a.get("answer_status"))
    st, a2 = call("GET", f"/v2/answers/{a['answer_id']}", admin=False)
    step("answer permalink", st == 200 and a2["answer_id"] == a["answer_id"])
    st, fp = call("POST", "/v2/ask", {"question": "איזה שופט קבע שהתיק תפור?"}, admin=False)
    step("false premise corrected", fp.get("answer_status") == "false_premise_corrected", fp.get("answer_short"))
    print("live e2e: all steps passed")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/synthetic_protocol.pdf")
