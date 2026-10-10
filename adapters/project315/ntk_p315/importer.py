"""Project 315 importer (spec §5, §28).

* the export snapshot is stored as a SourceDocument/SourceVersion (tier 3,
  owner "Project 315", stance "defense-supportive"), so every event has
  provenance back to the exact bytes imported;
* every raw record is kept (raw_payload + sha256); a changed record creates
  a new row in project315_event_versions with a diff — nothing is silently
  overwritten;
* default court_record_status is ``external``; the importer never raises it
  (only an official document or a mention identified in a protocol can);
* fails on missing event id / page URL / classification / raw payload; warns
  on broken URLs, duplicates, unparseable dates, classification changes and
  events without any linked source;
* a deterministic 10% sample (and, at publication time, every event used in
  a public claim card) gets an independent-verification review task.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy.engine import Connection

from ntk_common import contracts, ids
from ntk_common.db import knowledge as kdb
from ntk_common.db import sources
from ntk_common.db.core import execute, j, row

from .mapping import (INVOLVEMENT, PARSER_VERSION, REQUIRED, apply_mapping, as_list, parse_date_or_range, valid_url)

SOURCE_OWNER = "Project 315"
SOURCE_STANCE = "defense-supportive"


class ImportFailed(Exception):
    def __init__(self, message: str, errors: list[dict]):
        super().__init__(message)
        self.errors = errors


def parse_content(content: str, fmt: str) -> list[dict]:
    if fmt == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("events") or data.get("items") or data.get("data") or []
        if not isinstance(data, list):
            raise ImportFailed("JSON export must be a list or contain events/items/data", [])
        return [d for d in data if isinstance(d, dict)]
    if fmt == "csv":
        return list(csv.DictReader(io.StringIO(content)))
    raise ImportFailed(f"unsupported format {fmt}", [])


def to_event(raw: dict, mapping: dict | None, *, source_label: str, synthetic: bool, imported_at: str) -> tuple[dict | None, list[dict], list[str]]:
    errors: list[dict] = []
    warnings: list[str] = []
    m = apply_mapping(raw, mapping)
    for f in REQUIRED:
        if not m.get(f) or not str(m.get(f)).strip():
            errors.append({"field": f, "message": "required field missing"})
    if not raw:
        errors.append({"field": "raw_payload", "message": "empty record"})
    if errors:
        return None, errors, warnings
    ext_id = str(m["event_315_id"]).strip()
    page_url = str(m["project315_page_url"]).strip()
    if not valid_url(page_url):
        errors.append({"field": "project315_page_url", "message": f"invalid URL {page_url!r}"})
        return None, errors, warnings
    date_range, w = parse_date_or_range(m.get("date_or_range"))
    if w:
        warnings.append(f"{ext_id}: {w}")
    involvement = m.get("netanyahu_involvement")
    if involvement not in (None, "") and str(involvement).strip() not in INVOLVEMENT:
        warnings.append(f"{ext_id}: netanyahu_involvement {involvement!r} not in {sorted(INVOLVEMENT)}; stored as null (mapping needed)")
        involvement = None
    urls = []
    for kind, key in (("original_article", "original_article_urls"), ("wayback", "wayback_urls")):
        for u in as_list(m.get(key)):
            if valid_url(str(u)):
                urls.append({"url": str(u), "kind": kind, "court_record_status": "external"})
            else:
                warnings.append(f"{ext_id}: broken URL {u!r}")
    if not urls:
        warnings.append(f"{ext_id}: event has no linked source URL")
    raw_sha = ids.sha256_json(raw)
    event = {
        "schema_version": "2.0",
        "id": ids.stable_id("ev315", [ext_id]),
        "external_event_id": ext_id,
        "indictment_reference": _s(m.get("indictment_reference")),
        "date_or_range": date_range,
        "description": _s(m.get("description")),
        "requester": _s(m.get("requester")),
        "recipient": _s(m.get("recipient")),
        "subject": _s(m.get("subject")),
        "requested_action": _s(m.get("requested_action")),
        "prosecution_description": _s(m.get("prosecution_description")),
        "project315_classification": str(m["project315_classification"]).strip(),
        "project315_reasoning_summary": _s(m.get("project315_reasoning_summary")),
        "netanyahu_involvement": involvement or None,
        "persons": [str(p) for p in as_list(m.get("persons"))],
        "urls": urls,
        "court_mentions": [],
        "witness_mentions": [],
        "project315_page_url": page_url,
        "court_record_status": "external",
        "in_court_record": False,
        "independent_verification_status": "unreviewed",
        "source_owner": SOURCE_OWNER,
        "source_stance": SOURCE_STANCE,
        "provenance": {"raw_payload_sha256": raw_sha, "parser_version": PARSER_VERSION, "source": source_label,
                       "imported_at": imported_at, "synthetic": synthetic},
    }
    event["_court_mentions_raw"] = as_list(m.get("court_mentions"))
    event["_witness_mentions_raw"] = as_list(m.get("witness_mentions"))
    return event, [], warnings


def _s(v: Any) -> str | None:
    if v in (None, ""):
        return None
    return str(v).strip() or None


def import_export(conn: Connection, *, content: str, fmt: str, source: str, synthetic: bool, actor: str,
                  mapping: dict | None = None, case_id: str = "il-jdc-jerusalem-67104-01-20") -> dict:
    import datetime as dt

    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    payload_sha = ids.sha256_text(content)
    records = parse_content(content, fmt)
    if not records:
        raise ImportFailed("export contains no records", [])

    run_id = str(ids.derived_uuid("p315_import", payload_sha, PARSER_VERSION))
    previous = row(conn, "SELECT id FROM ntk.project315_import_runs WHERE payload_sha256 = :s AND parser_version = :p",
                   {"s": payload_sha, "p": PARSER_VERSION})
    # snapshot provenance
    sources.ensure_case(conn, case_id=case_id, court_case_number=case_id.split("-", 3)[-1] if case_id.count("-") >= 3 else case_id,
                        title="מדינת ישראל נ' נתניהו ואח'", court_name="בית המשפט המחוזי בירושלים")
    doc_id = ids.source_document_id(case_id, "project315-export")
    sources.ensure_document(conn, document_id=doc_id, case_id=case_id, title="Project 315 export snapshot",
                            source_type="project315", authority_tier=3, source_owner=SOURCE_OWNER,
                            source_stance=SOURCE_STANCE, canonical_url="https://www.the315.org/list",
                            default_court_record_status="external",
                            legal_access_notes="Imported research of an external project with a declared stance; reuse terms to be confirmed with the project.")
    svid, _ = sources.insert_source_version(conn, document_id=doc_id, content_sha256=payload_sha, retrieved_at=now,
                                            mime_type="application/json" if fmt == "json" else "text/csv",
                                            size_bytes=len(content.encode()), object_uri=None, source_url=source, s3=None,
                                            page_count=None, parser_version=PARSER_VERSION, extractor_version=None,
                                            court_record_status="external", metadata={"synthetic": synthetic})

    errors: list[dict] = []
    warnings: list[str] = []
    events: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(records):
        ev, errs, warns = to_event(raw, mapping, source_label=source, synthetic=synthetic, imported_at=now)
        warnings += warns
        if errs:
            errors.append({"record": i, "errors": errs})
            continue
        assert ev is not None
        if ev["external_event_id"] in seen:
            warnings.append(f"{ev['external_event_id']}: duplicate event in export; first occurrence kept")
            continue
        seen.add(ev["external_event_id"])
        clean = {k: v for k, v in ev.items() if not k.startswith("_")}
        try:
            contracts.validate("Project315Event", clean)
        except contracts.ContractError as ce:
            errors.append({"record": i, "errors": ce.errors})
            continue
        ev["_raw"] = raw
        events.append(ev)
    if errors and not events:
        raise ImportFailed(f"all {len(records)} records failed validation", errors[:50])

    if previous is None:
        execute(conn, """INSERT INTO ntk.project315_import_runs (id, source, payload_sha256, parser_version)
                         VALUES (CAST(:id AS uuid), :src, :sha, :pv)""",
                {"id": run_id, "src": source, "sha": payload_sha, "pv": PARSER_VERSION})

    imported = unchanged = updated = 0
    for ev in events:
        raw_sha = ev["provenance"]["raw_payload_sha256"]
        existing = row(conn, "SELECT raw_payload_sha256, project315_classification, raw_payload FROM ntk.project315_events WHERE id = :id",
                       {"id": ev["id"]})
        mapped = {k: v for k, v in ev.items() if not k.startswith("_")}
        dr = ev["date_or_range"]
        params = {
            "id": ev["id"], "ext": ev["external_event_id"], "ref": ev["indictment_reference"],
            "dfrom": dr["from"] if dr else None, "dto": dr["to"] if dr and dr.get("to") else None,
            "req": ev["requester"], "rec": ev["recipient"], "subj": ev["subject"], "act": ev["requested_action"],
            "pros": ev["prosecution_description"], "cls": ev["project315_classification"],
            "reason": ev["project315_reasoning_summary"], "inv": ev["netanyahu_involvement"], "url": ev["project315_page_url"],
            "sv": svid, "raw": j(ev["_raw"]), "rsha": raw_sha, "pv": PARSER_VERSION, "src": source, "syn": synthetic,
            "desc": ev["description"], "persons": ev["persons"],
        }
        if existing is None:
            execute(conn, """
                INSERT INTO ntk.project315_events (id, external_event_id, indictment_reference, date_or_range, requester,
                    recipient, subject, requested_action, prosecution_description, project315_classification,
                    project315_reasoning_summary, netanyahu_involvement, project315_page_url, source_version_id, raw_payload,
                    raw_payload_sha256, parser_version, import_source, synthetic, description, persons)
                VALUES (:id, :ext, :ref, CASE WHEN CAST(:dfrom AS date) IS NULL THEN NULL
                        ELSE daterange(CAST(:dfrom AS date), coalesce(CAST(:dto AS date), CAST(:dfrom AS date)), '[]') END,
                    :req, :rec, :subj, :act, :pros, :cls, :reason, :inv, :url, :sv, CAST(:raw AS jsonb), :rsha, :pv, :src,
                    :syn, :desc, :persons)
            """, params)
            imported += 1
            diff: dict = {}
        elif existing["raw_payload_sha256"] == raw_sha:
            unchanged += 1
            continue
        else:
            old_raw = existing["raw_payload"] or {}
            diff = {k: {"old": old_raw.get(k), "new": ev["_raw"].get(k)} for k in set(old_raw) | set(ev["_raw"])
                    if old_raw.get(k) != ev["_raw"].get(k)}
            if existing["project315_classification"] != ev["project315_classification"]:
                warnings.append(f"{ev['external_event_id']}: classification changed "
                                f"{existing['project315_classification']!r} → {ev['project315_classification']!r}")
            execute(conn, """
                UPDATE ntk.project315_events SET indictment_reference = :ref,
                    date_or_range = CASE WHEN CAST(:dfrom AS date) IS NULL THEN NULL
                        ELSE daterange(CAST(:dfrom AS date), coalesce(CAST(:dto AS date), CAST(:dfrom AS date)), '[]') END,
                    requester = :req, recipient = :rec, subject = :subj, requested_action = :act,
                    prosecution_description = :pros, project315_classification = :cls, project315_reasoning_summary = :reason,
                    netanyahu_involvement = :inv, project315_page_url = :url, source_version_id = :sv,
                    previous_payload_sha256 = raw_payload_sha256, raw_payload = CAST(:raw AS jsonb), raw_payload_sha256 = :rsha,
                    parser_version = :pv, import_source = :src, synthetic = :syn, description = :desc, persons = :persons,
                    independent_verification_status = 'unreviewed'
                WHERE id = :id
            """, params)
            updated += 1
        execute(conn, """
            INSERT INTO ntk.project315_event_versions (event_id, payload_sha256, raw_payload, mapped, source_version_id,
                import_run_id, diff)
            VALUES (:id, :rsha, CAST(:raw AS jsonb), CAST(:mapped AS jsonb), :sv, CAST(:run AS uuid), CAST(:diff AS jsonb))
            ON CONFLICT DO NOTHING
        """, {"id": ev["id"], "rsha": raw_sha, "raw": j(ev["_raw"]), "mapped": j(mapped), "sv": svid, "run": run_id,
              "diff": j(diff)})
        for u in ev["urls"]:
            execute(conn, """INSERT INTO ntk.project315_event_sources (event_id, url, court_record_status)
                             VALUES (:e, :u, 'external') ON CONFLICT DO NOTHING""", {"e": ev["id"], "u": u["url"]})
        _link_mentions(conn, ev, warnings)
        if int(raw_sha[:8], 16) % 10 == 0:
            kdb.open_review_task(conn, object_type="project315_event", object_id=ev["id"], risk_flags=["p315_spot_check"],
                                 reason=f"independent verification sample for event {ev['external_event_id']}")

    execute(conn, """UPDATE ntk.project315_import_runs SET imported_count = :n, warnings = CAST(:w AS jsonb), errors = CAST(:e AS jsonb)
                     WHERE id = CAST(:id AS uuid)""",
            {"n": imported + updated, "w": j(warnings[:500]), "e": j(errors[:200]), "id": run_id})
    return {"run_id": run_id, "source_version_id": svid, "records": len(records), "imported": imported,
            "updated": updated, "unchanged": unchanged, "failed": len(errors), "errors": errors[:50],
            "warnings": warnings[:200], "warnings_count": len(warnings), "synthetic": synthetic}


def _link_mentions(conn: Connection, ev: dict, warnings: list[str]) -> None:
    for m in ev["_court_mentions_raw"]:
        uid = m.get("source_unit_id") if isinstance(m, dict) else str(m)
        if uid and row(conn, "SELECT 1 AS ok FROM ntk.source_units WHERE id = :u", {"u": uid}):
            execute(conn, """INSERT INTO ntk.project315_event_mentions (event_id, mention_type, source_unit_id)
                             VALUES (:e, 'court', :u) ON CONFLICT DO NOTHING""", {"e": ev["id"], "u": uid})
        else:
            warnings.append(f"{ev['external_event_id']}: court mention {uid!r} is not an identified source unit; not linked")
    for m in ev["_witness_mentions_raw"]:
        name = m.get("name") if isinstance(m, dict) else str(m)
        ent = row(conn, """SELECT id FROM ntk.entities WHERE entity_type='person'
                           AND (canonical_name = :n OR :n = ANY(aliases)) LIMIT 1""", {"n": name})
        if ent:
            execute(conn, """INSERT INTO ntk.project315_event_mentions (event_id, mention_type, entity_id)
                             VALUES (:e, 'witness', :ent) ON CONFLICT DO NOTHING""", {"e": ev["id"], "ent": ent["id"]})
        else:
            warnings.append(f"{ev['external_event_id']}: witness {name!r} not resolved to a known entity; not linked")
