"""Duplicates in the intake (operator request 11.10.2026).

Two kinds:

* **Exact** — the same bytes (SHA-256) as a source already stored, or as an earlier intake item. The canonical copy
  lives once under ``sources/sha256/…`` (content-addressed, so it is never written twice). The extra copy under
  ``inbox/`` is deleted automatically when ``NTK_INBOX_DELETE_DUPLICATES=true``, but only after checking that the
  canonical copy exists with the same size. The row stays as ``removed`` (key, ETag, hash, when, why).
* **Possible** — different bytes, (almost) the same text: a re-scan, a re-saved PDF, a copy with a stamp. Compared by
  a text fingerprint of pages 1, 2 and the last page. Such an item is held as ``possible_duplicate``: not copied to
  ``sources/`` (which is write-once), not ingested, until the operator deletes the copy or marks it as a different
  document. Nothing is deleted automatically on a text match.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import hebrew
from .db.core import execute, j, row, rows, scalar

SKETCH = 256
SHINGLE = 4
MIN_SHINGLES = 40
POSSIBLE_THRESHOLD = 0.9
AUTO_REMOVE_SIMILARITY = 0.98  # with the same page count: removed automatically (operator rule)
_WORD = re.compile(r"[0-9a-zא-ת]+")


def fingerprint(text: str) -> list[int]:
    """Bottom-k sketch of 4-word shingles over normalised text (Hebrew final letters folded, punctuation dropped)."""
    words = [w for w in _WORD.findall(hebrew.normalize(text or "").lower()) if len(w) > 1]
    sh = {" ".join(words[i:i + SHINGLE]) for i in range(max(0, len(words) - SHINGLE + 1))}
    hs = sorted({int(hashlib.sha1(s.encode("utf-8")).hexdigest()[:15], 16) for s in sh})  # noqa: S324 - not security
    return hs[:SKETCH] if len(hs) >= MIN_SHINGLES else []


def similarity(a: list[int], b: list[int]) -> float:
    """Jaccard estimate from two bottom-k sketches."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    k = min(SKETCH, len(sa | sb))
    union_bottom = sorted(sa | sb)[:k]
    return sum(1 for h in union_bottom if h in sa and h in sb) / k


def source_fingerprint(conn, source_version_id: str) -> tuple[int, list[int]] | None:
    cached = row(conn, "SELECT page_count, fingerprint FROM ntk.document_fingerprints WHERE source_version_id = :sv",
                 {"sv": source_version_id})
    if cached:
        return int(cached["page_count"]), list(cached["fingerprint"])
    pc = scalar(conn, "SELECT page_count FROM ntk.source_versions WHERE id = :sv", {"sv": source_version_id})
    if not pc:
        return None
    units = rows(conn, """SELECT raw_text FROM ntk.source_units WHERE source_version_id = :sv AND superseded_at IS NULL
                          AND page_no IN (1, 2, :last) ORDER BY unit_ordinal""", {"sv": source_version_id, "last": pc})
    fp = fingerprint("\n".join(u["raw_text"] or "" for u in units))
    execute(conn, """INSERT INTO ntk.document_fingerprints (source_version_id, page_count, fingerprint)
                     VALUES (:sv, :pc, :fp) ON CONFLICT (source_version_id) DO NOTHING""",
            {"sv": source_version_id, "pc": int(pc), "fp": fp})
    return int(pc), fp


def find_possible_duplicate(conn, *, fp: list[int], page_count: int, sha: str, item_id: str,
                            date: str | None = None) -> tuple[str, float] | None:
    """Best match ≥ threshold among stored source versions and earlier intake items with ±1 page. Documents with two
    different known dates are never treated as copies (templated court decisions differ mostly in their dates)."""
    if not fp:
        return None
    best: tuple[str, float] | None = None
    svs = rows(conn, """SELECT sv.id, coalesce(sv.metadata->>'document_date', h.hearing_date::text) AS d
                        FROM ntk.source_versions sv LEFT JOIN ntk.hearings h ON h.source_version_id = sv.id
                        WHERE sv.page_count BETWEEN :lo AND :hi AND sv.content_sha256 <> :sha""",
               {"lo": page_count - 1, "hi": page_count + 1, "sha": sha})
    for r in svs:
        if date and r["d"] and r["d"][:10] != date:
            continue
        got = source_fingerprint(conn, r["id"])
        if got:
            sim = similarity(fp, got[1])
            if sim >= POSSIBLE_THRESHOLD and (best is None or sim > best[1]):
                best = (r["id"], sim)
    items = rows(conn, """SELECT id::text AS id, classification->'fingerprint' AS fp,
                                 coalesce(classification->>'hearing_date', classification->>'document_date') AS d
                          FROM ntk.inbox_items
                          WHERE id <> CAST(:id AS uuid) AND content_sha256 IS DISTINCT FROM :sha
                            AND status IN ('classified', 'queued', 'ingested', 'ingest_failed', 'possible_duplicate')
                            AND (classification->>'page_count')::int BETWEEN :lo AND :hi
                            AND jsonb_typeof(classification->'fingerprint') = 'array'""",
                 {"id": item_id, "sha": sha, "lo": page_count - 1, "hi": page_count + 1})
    for r in items:
        if date and r["d"] and r["d"][:10] != date:
            continue
        sim = similarity(fp, [int(x) for x in r["fp"] or []])
        if sim >= POSSIBLE_THRESHOLD and (best is None or sim > best[1]):
            best = (f"inbox:{r['id']}", sim)
    return best


def kept_copy_key(conn, storage, item: dict) -> str | None:
    """Where the copy that stays is stored, if it really exists with the same size as the duplicate."""
    ref = item.get("duplicate_of") or ""
    candidates: list[str] = []
    if ref.startswith("sv_"):
        k = scalar(conn, "SELECT s3_key FROM ntk.source_versions WHERE id = :sv", {"sv": ref})
        if k:
            candidates.append(k)
    elif ref.startswith("inbox:"):
        k = scalar(conn, "SELECT source_key FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": ref[6:]})
        if k:
            candidates.append(k)
    if item.get("status") == "duplicate" and item.get("content_sha256"):
        candidates.append(storage.content_key(item["content_sha256"]))
    for k in dict.fromkeys(candidates):
        info = storage.head(k)
        if info is not None and (item.get("status") != "duplicate" or int(info.size) == int(item["size_bytes"])):
            return k
    return None


def _delete(services, it: dict, *, kept: str, actor: str, reason: str) -> dict:
    from .db import ops

    existed = services.storage.delete_intake_copy(it["object_key"], prefix=services.settings.inbox_prefix,
                                                  expected_etag=it["etag"] or None)
    with services.engine.begin() as conn:
        execute(conn, """UPDATE ntk.inbox_items SET status = 'removed', removed_at = now(), removed_by = :by, updated_at = now(),
                         error = CAST(:e AS jsonb) WHERE id = CAST(:id AS uuid)""",
                {"id": str(it["id"]), "by": actor, "e": j({"removed_reason": reason, "previous_status": it["status"],
                                                           "kept_copy": kept, "object_existed": existed})})
        ops.audit(conn, actor=actor, action="inbox.copy_removed", object_type="inbox_item", object_id=str(it["id"]),
                  details={"object_key": it["object_key"], "etag": it["etag"], "sha256": it["content_sha256"],
                           "duplicate_of": it["duplicate_of"], "kept_copy": kept, "reason": reason})
        if it.get("content_sha256"):
            apply_best_name(conn, it["content_sha256"])
    return {"item_id": str(it["id"]), "removed": True, "kept_copy": kept, "object_existed": existed}


def _exact_copies_of(conn, item_id: str) -> list[dict]:
    return rows(conn, """SELECT * FROM ntk.inbox_items WHERE status = 'duplicate' AND duplicate_of = :ref""",
                {"ref": f"inbox:{item_id}"})


def remove_copy(services, item_id: str, *, actor: str, reason: str) -> dict:
    """Delete the intake copy of a duplicate. Refuses unless the kept copy exists (and, for exact duplicates, has the
    same size). The row is kept as ``removed``. Removing a held near-duplicate also removes its exact copies (same bytes,
    same decision)."""
    with services.engine.connect() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": item_id})
        if it is None:
            return {"item_id": item_id, "removed": False, "reason": "not_found"}
        if it["status"] not in {"duplicate", "possible_duplicate"}:
            return {"item_id": item_id, "removed": False, "reason": f"status is {it['status']}"}
        kept = kept_copy_key(conn, services.storage, it)
        if kept is None and it["status"] == "duplicate" and (it["duplicate_of"] or "").startswith("inbox:"):
            # a copy of a held near-duplicate: it follows the decision about that item
            parent = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": it["duplicate_of"][6:]})
            if parent and parent["status"] in {"possible_duplicate", "removed"} and parent["duplicate_of"]:
                kept = kept_copy_key(conn, services.storage, {**parent, "status": "possible_duplicate"})
        copies = _exact_copies_of(conn, item_id) if it["status"] == "possible_duplicate" else []
    if kept is None:
        return {"item_id": item_id, "removed": False, "reason": "kept_copy_not_found"}
    out = _delete(services, it, kept=kept, actor=actor, reason=reason)
    out["copies_removed"] = [_delete(services, c, kept=kept, actor=actor, reason=reason + " (identical copy)")["item_id"]
                             for c in copies]
    return out


def best_named_item(conn, sha: str) -> dict | None:
    """Among intake copies of the same bytes, the one whose file name follows the archive pattern (number — date —
    type — description) carries the most information."""
    from .inbox import filename_meta

    best, score = None, 0
    for it in rows(conn, "SELECT id, object_key, doc_kind, classification FROM ntk.inbox_items WHERE content_sha256 = :s",
                   {"s": sha}):
        fm = filename_meta(it["object_key"])
        sc = (2 if fm.get("description") else 0) + (1 if fm.get("date") else 0)
        if sc > score:
            best, score = it, sc
    return best


def apply_best_name(conn, sha: str) -> bool:
    """If the stored document was named from a less informative copy (e.g. '0051_1.pdf') while another copy of the same
    bytes has the archive name, retitle the document and fill its date and archive number from that name. Content,
    citations and the stored file are untouched."""
    from .inbox import _title, document_date_for, filename_meta

    sv = row(conn, """SELECT sv.id, sv.document_id, sv.metadata, d.source_type::text AS st FROM ntk.source_versions sv
                      JOIN ntk.source_documents d ON d.id = sv.document_id WHERE sv.content_sha256 = :s
                      ORDER BY sv.created_at DESC LIMIT 1""", {"s": sha})
    if sv is None:
        return False
    meta = sv["metadata"] or {}
    if meta.get("name_from") or filename_meta(meta.get("original_filename") or "").get("description"):
        return False
    best = best_named_item(conn, sha)
    if best is None or best["object_key"] == meta.get("original_filename"):
        return False
    it = {"doc_kind": sv["st"], "object_key": best["object_key"]}
    c = best["classification"] or {}
    fm = filename_meta(best["object_key"])
    patch = {"name_from": best["object_key"], "archive_number": fm.get("number")}
    if sv["st"] != "protocol":
        d = document_date_for(it, c)
        if d:
            patch["document_date"] = d
        execute(conn, "UPDATE ntk.source_documents SET canonical_title = :t WHERE id = :id",
                {"t": _title(it, c), "id": sv["document_id"]})
    execute(conn, "UPDATE ntk.source_versions SET metadata = metadata || CAST(:p AS jsonb) WHERE id = :id",
            {"p": j({k: v for k, v in patch.items() if v}), "id": sv["id"]})
    return True


def refresh_names(conn) -> dict:
    shas = [r["s"] for r in rows(conn, """SELECT DISTINCT content_sha256 AS s FROM ntk.inbox_items
                                          WHERE content_sha256 IS NOT NULL AND status IN ('ingested', 'removed', 'duplicate')""")]
    changed = [s for s in shas if apply_best_name(conn, s)]
    return {"checked": len(shas), "retitled": len(changed)}


def _ref_info(conn, ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    if ref.startswith("sv_"):
        r = row(conn, """SELECT sv.id AS source_version_id, d.canonical_title AS title, d.source_type::text AS source_type,
                                sv.page_count, sv.publication_state::text AS publication_state,
                                coalesce(sv.metadata->>'document_date', '') AS document_date,
                                sv.metadata->>'original_filename' AS original_filename,
                                (SELECT h.id FROM ntk.hearings h WHERE h.source_version_id = sv.id LIMIT 1) AS hearing_id
                         FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id WHERE sv.id = :sv""",
                {"sv": ref})
        return {"kind": "source", **r} if r else {"kind": "source", "source_version_id": ref}
    if ref.startswith("inbox:"):
        r = row(conn, """SELECT id::text AS item_id, object_key, status, doc_kind, classification->>'title' AS title,
                                (classification->>'page_count')::int AS page_count FROM ntk.inbox_items
                         WHERE id = CAST(:id AS uuid)""", {"id": ref[6:]})
        return {"kind": "inbox", **r} if r else {"kind": "inbox", "item_id": ref[6:]}
    return {"kind": "other", "ref": ref}


def listing(conn, *, limit: int = 200) -> dict:
    def items(where: str) -> list[dict]:
        rs = rows(conn, f"""SELECT id::text AS id, object_key, size_bytes, status, doc_kind, duplicate_of, similarity,
                                   classification->>'title' AS title, (classification->>'page_count')::int AS page_count,
                                   first_seen_at, removed_at, removed_by, error
                            FROM ntk.inbox_items WHERE {where} ORDER BY coalesce(removed_at, first_seen_at) DESC LIMIT :lim""",
                    {"lim": limit})
        for r in rs:
            r["kept"] = _ref_info(conn, r["duplicate_of"])
        return rs

    counts = {r["status"]: r["n"] for r in rows(conn, """SELECT status, count(*) AS n FROM ntk.inbox_items
                                                         WHERE status IN ('duplicate', 'possible_duplicate', 'removed')
                                                         GROUP BY 1""")}
    return {"counts": counts, "possible": items("status = 'possible_duplicate'"),
            "exact_not_removed": items("status = 'duplicate'"), "removed": items("status = 'removed'")}


def release(services, item_id: str, *, actor: str) -> dict:
    """The operator says a held item is a different document: store it under sources/ and mark it classified, so it is
    ingested like any other item."""
    from . import ids
    from .db import ops

    s = services.settings
    with services.engine.connect() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:id AS uuid)", {"id": item_id})
    if it is None or it["status"] != "possible_duplicate":
        return {"item_id": item_id, "released": False, "reason": "not a held possible duplicate"}
    data = services.storage.get_bytes(it["object_key"], max_bytes=s.max_upload_bytes)
    if ids.sha256_bytes(data) != it["content_sha256"]:
        return {"item_id": item_id, "released": False, "reason": "the file changed since it was scanned"}
    source_key = services.storage.content_key(it["content_sha256"])
    services.storage.put_bytes(source_key, data, mime_type="application/pdf")
    c = it["classification"] or {}
    status = "foreign_case" if c.get("case_found") is False else "classified"
    with services.engine.begin() as conn:
        execute(conn, """UPDATE ntk.inbox_items SET status = :st, source_key = :k, updated_at = now(),
                         error = CAST(:e AS jsonb) WHERE id = CAST(:id AS uuid)""",
                {"id": item_id, "st": status, "k": source_key,
                 "e": j({"released_as_different_document": True, "was_similar_to": it["duplicate_of"],
                         "similarity": it["similarity"], "by": actor})})
        ops.audit(conn, actor=actor, action="inbox.possible_duplicate_released", object_type="inbox_item",
                  object_id=item_id, details={"similar_to": it["duplicate_of"], "similarity": it["similarity"]})
    removed = []
    if s.inbox_delete_duplicates:
        with services.engine.connect() as conn:
            copies = _exact_copies_of(conn, item_id)
        for cp in copies:
            if remove_copy(services, str(cp["id"]), actor="inbox:auto", reason="exact duplicate (same SHA-256)").get("removed"):
                removed.append(str(cp["id"]))
    return {"item_id": item_id, "released": True, "status": status, "copies_removed": removed}


def same_page_count(services, ref: str, page_count: int) -> bool:
    with services.engine.connect() as conn:
        if ref.startswith("sv_"):
            pc = scalar(conn, "SELECT page_count FROM ntk.source_versions WHERE id = :sv", {"sv": ref})
        else:
            pc = scalar(conn, "SELECT (classification->>'page_count')::int FROM ntk.inbox_items WHERE id = CAST(:i AS uuid)",
                        {"i": ref[6:]})
    return pc is not None and int(pc) == int(page_count)
