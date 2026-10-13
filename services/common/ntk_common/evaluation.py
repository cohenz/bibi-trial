"""Evaluation: golden question suites, search benchmark, citation location
check, and human-label sampling/scoring (spec §16, §34.4).

Automatic metrics computed here:
* status correctness per question (incl. 100% correction/refusal of false
  premises);
* citation location accuracy: every public citation re-opened against the
  *original PDF bytes* — the cited lines on the cited page must contain the
  unit's text;
* "court determined" wording without an approved ruling (must be 0);
* lexical support proxy for citation precision (flagged as a proxy).

Metrics that need people (speaker accuracy on 200 turns, Q/A pairing on 100
exchanges, true citation precision) use label-export / label-score; they are
reported as "not measured" until a labelled file exists.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from . import gates, hebrew
from .ask import AskConfig, AskEngine
from .db.core import rows
from .db.public import PgAskStore
from .pipeline import pdf as pdfmod
from .search.base import SearchFilters, SearchRequest


# ---------------------------------------------------------------------------
# citation location check
# ---------------------------------------------------------------------------
class CitationLocator:
    """Re-extracts source PDFs (cached per version) and checks that a unit's
    text is present on its page within its line range."""

    def __init__(self, engine: Engine, storage):
        self.engine = engine
        self.storage = storage
        self._pages: dict[str, dict[int, list[pdfmod.Line]]] = {}

    def _load(self, svid: str) -> dict[int, list[pdfmod.Line]] | None:
        if svid in self._pages:
            return self._pages[svid]
        with self.engine.connect() as conn:
            r = rows(conn, "SELECT s3_key, object_uri FROM ntk.source_versions WHERE id = :id", {"id": svid})
        if not r or not r[0]["s3_key"] or self.storage is None:
            return None
        data = self.storage.get_bytes(r[0]["s3_key"], max_bytes=300 * 1024 * 1024)
        doc = pdfmod.extract_document(data, allow_ocr=False)
        by_page: dict[int, list[pdfmod.Line]] = {}
        for p in doc.pages:
            by_page[p.page] = p.lines
        self._pages[svid] = by_page
        return by_page

    def check(self, unit: dict) -> tuple[bool, str]:
        pages = self._load(unit["source_version_id"])
        if pages is None:
            return False, "source bytes unavailable"
        lines = [ln for ln in pages.get(unit["page_no"], []) if unit["line_start"] <= ln.line_no <= unit["line_end"]]
        if not lines:
            return False, "no lines at cited location"
        window = hebrew.fold(" ".join(ln.text for ln in lines))
        words = [w for w in hebrew.fold(unit["raw_text"]).split() if len(w) > 1]
        if not words:
            return True, "empty"
        probe = words[: min(6, len(words))]
        tail = words[-min(4, len(words)):]
        ok = all(w in window for w in probe) and all(w in window for w in tail)
        return ok, "ok" if ok else "text not found at cited lines"


# ---------------------------------------------------------------------------
# golden suite
# ---------------------------------------------------------------------------
def _missing_hearings(engine: Engine, dates: list[str], case_id: str | None = None, case_number: str | None = None) -> list[str]:
    """Dates with no published hearing of this case. When case_number is given, the protocol's own caption must carry it,
    so a fixture or a stray PDF ingested under the case id never counts as the real hearing."""
    if not dates:
        return []
    with engine.connect() as conn:
        have = {r["d"] for r in rows(conn, """SELECT h.hearing_date::text AS d FROM ntk.hearings h
                                             JOIN ntk.source_versions sv ON sv.id = h.source_version_id
                                             WHERE sv.publication_state = 'published'
                                               AND (CAST(:case AS text) IS NULL OR h.case_id = :case)
                                               AND (CAST(:num AS text) IS NULL
                                                    OR (h.metadata->>'court_case_number' = :num
                                                        AND h.metadata->>'court_case_number_source' = 'document')
                                                    OR EXISTS (
                                                    SELECT 1 FROM ntk.source_units su WHERE su.source_version_id = sv.id
                                                      AND su.page_no = 1 AND su.raw_text LIKE '%' || :num || '%'))""",
                                    {"case": case_id, "num": case_number})}
    return sorted(set(dates) - have)


def not_measured(suite: dict, path: Path, missing: list[str]) -> dict:
    """A suite whose corpus is not loaded is reported as NOT MEASURED — never as passed."""
    return {"summary": {"suite": suite.get("name", path.stem), "measured": False, "passed": False,
                        "blocked_by": f"published hearings missing from corpus: {', '.join(missing)}",
                        "questions": len(suite.get("questions") or suite.get("queries") or [])},
            "results": [], "generated_at": dt.datetime.now(dt.UTC).isoformat()}


def run_suite(path: Path, *, settings, engine: Engine, services, as_of: str | None = None) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    missing = _missing_hearings(engine, suite.get("requires_hearing_dates", []), suite.get("case_id"),
                                 suite.get("court_case_number"))
    if missing:
        return not_measured(suite, path, missing)
    as_of_dt = dt.datetime.fromisoformat((as_of or suite.get("as_of") or dt.datetime.now(dt.UTC).isoformat()).replace("Z", "+00:00"))
    engine_ask = AskEngine(PgAskStore(engine, case_id=settings.case_id), services.search_backend(), services.runner,
                           AskConfig(answer_base=settings.answer_base, citation_base=settings.citation_base, env=settings.env,
                                     independent_verifier=not services.registry.single_family, lens=settings.ask_lens))
    locator = CitationLocator(engine, services.storage)
    results = []
    cit_total = cit_ok = 0
    overstatements = 0
    support_total = support_ok = 0
    for q in suite["questions"]:
        t0 = time.perf_counter()
        res = engine_ask.answer(q["question"], as_of=as_of_dt)
        env = res.envelope
        latency = (time.perf_counter() - t0) * 1000
        status_ok = env["answer_status"] in q["expect_status"]
        text_all = env["answer_short"] + " " + " ".join(s["text"] for s in env["sections"])
        forbidden = [p for p in q.get("must_not_contain", []) if p in text_all]
        # citation locations
        cited_ids = [c["source_unit_id"] for c in env["citations"]]
        loc_fail = []
        if cited_ids:
            with engine.connect() as conn:
                units = rows(conn, """SELECT su.id, su.source_version_id, su.page_no, su.line_start, su.line_end, su.raw_text,
                                             sv.publication_state,
                                             (SELECT h.hearing_date::text FROM ntk.hearings h
                                               WHERE h.source_version_id = su.source_version_id LIMIT 1) AS hearing_date
                                             FROM ntk.source_units su JOIN ntk.source_versions sv
                                             ON sv.id = su.source_version_id WHERE su.id = ANY(:ids)""", {"ids": cited_ids})
            by_id = {u["id"]: u for u in units}
            for c in env["citations"]:
                cit_total += 1
                u = by_id.get(c["source_unit_id"])
                good = (u is not None and u["publication_state"] == "published" and u["page_no"] == c["page"]
                        and u["line_start"] == c["line_start"] and u["line_end"] == c["line_end"])
                reason = "metadata mismatch or unpublished" if not good else ""
                if good:
                    good, reason = locator.check(u)
                cit_ok += int(good)
                if not good:
                    loc_fail.append({"source_unit_id": c["source_unit_id"], "reason": reason})
            # determination wording without approved ruling
            for s in env["sections"] + [{"text": env["answer_short"], "citation_ids": []}]:
                if gates.find_determination_language(s["text"]):
                    overstatements += 1
            # lexical support proxy
            texts = {u["id"]: u["raw_text"] for u in units}
            for s in env["sections"]:
                if s["kind"] == "limitation" or not s["citation_ids"]:
                    continue
                support_total += 1
                terms = {t for t in hebrew.search_terms(s["text"]) if len(t) > 2}
                cited_terms = set()
                for cid in s["citation_ids"]:
                    cited_terms |= set(hebrew.search_terms(texts.get(cid, "")))
                support_ok += int(bool(terms) and len(terms & cited_terms) / len(terms) >= 0.3)
        # scope checks: answered questions must cite the hearing(s) they are about, with enough citations
        scope_fail = []
        if env["answer_status"] == "answered":
            if len(env["citations"]) < q.get("min_citations", 0):
                scope_fail.append(f"citations {len(env['citations'])} < {q['min_citations']}")
            want = set(q.get("expect_cited_hearing_dates", []))
            if want and cited_ids:
                got = {by_id[c]["hearing_date"] for c in cited_ids if c in by_id}
                if not got & want:
                    scope_fail.append(f"cited hearings {sorted(x for x in got if x)} not in {sorted(want)}")
        results.append({"id": q["id"], "category": q.get("category"), "question": q["question"],
                        "status": env["answer_status"], "expected": q["expect_status"], "status_ok": status_ok,
                        "forbidden_phrases": forbidden, "citations": len(env["citations"]), "citation_failures": loc_fail,
                        "scope_failures": scope_fail,
                        "answer_short": env["answer_short"], "permalink": env["permalink"], "latency_ms": round(latency, 1),
                        "passed": status_ok and not forbidden and not loc_fail and not scope_fail})
    fp = [r for r in results if r["category"] in {"false_premise", "ruling_attribution", "injection", "fill_in", "misattribution", "ignore_sources"}]
    answerable = [r for r in results if r["category"] == "answerable"]
    thresholds = suite.get("thresholds", {})
    summary = {
        "suite": suite.get("name", path.stem),
        "measured": True,
        "questions": len(results),
        "passed_questions": sum(r["passed"] for r in results),
        "false_premise_handled": f"{sum(r['status_ok'] for r in fp)}/{len(fp)}",
        "false_premise_rate": round(sum(r["status_ok"] for r in fp) / len(fp), 4) if fp else None,
        "answerable_with_citations": f"{sum(1 for r in answerable if r['status'] == 'answered' and r['citations'])}/{len(answerable)}",
        "citation_location_accuracy": round(cit_ok / cit_total, 4) if cit_total else None,
        "citations_checked": cit_total,
        "court_determined_overstatements": overstatements,
        "lexical_support_proxy": round(support_ok / support_total, 4) if support_total else None,
        "p50_latency_ms": round(statistics.median([r["latency_ms"] for r in results]), 1) if results else None,
    }
    checks = {
        "false_premise_rate": (summary["false_premise_rate"] is None or summary["false_premise_rate"] >= thresholds.get("false_premise_rate", 1.0)),
        "citation_location_accuracy": (summary["citation_location_accuracy"] is None or summary["citation_location_accuracy"] >= thresholds.get("citation_location_accuracy", 1.0)),
        "court_determined_overstatements": overstatements == 0,
        "all_questions": summary["passed_questions"] == len(results) if thresholds.get("require_all", True) else True,
    }
    summary["checks"] = checks
    summary["passed"] = all(checks.values())
    return {"summary": summary, "results": results, "generated_at": dt.datetime.now(dt.UTC).isoformat()}


# ---------------------------------------------------------------------------
# search benchmark
# ---------------------------------------------------------------------------
def _relevant(hit_text: str, hit_date: str | None, rel: dict) -> bool:
    if rel.get("hearing_date") and hit_date and rel["hearing_date"] != hit_date:
        return False
    return hebrew.fold(rel["contains"]) in hebrew.fold(hit_text)


def run_search_bench(path: Path, *, services, published_only: bool = False) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    engine = getattr(services, "engine", None)
    if suite.get("requires_hearing_dates") and engine is not None:
        missing = _missing_hearings(engine, suite["requires_hearing_dates"], suite.get("case_id"),
                                     suite.get("court_case_number"))
        if missing:
            return not_measured(suite, path, missing)
    unlabeled = [q["id"] for q in suite["queries"] if not q.get("relevant")]
    if unlabeled:
        out = not_measured(suite, path, [])
        out["summary"]["blocked_by"] = f"relevance labels missing for {len(unlabeled)} queries"
        return out
    backend = services.search_backend()
    rows_out = []
    lat = []
    for q in suite["queries"]:
        t0 = time.perf_counter()
        resp = backend.search(SearchRequest(q["query"], SearchFilters(published_only=published_only), limit=20))
        ms = (time.perf_counter() - t0) * 1000
        lat.append(ms)
        rels = q["relevant"]
        found = set()
        gains = []
        for h in resp.hits:
            # binary gain, credited once per relevant item (several hits on the same passage don't inflate nDCG)
            hit_rel = {i for i, r in enumerate(rels) if _relevant(h.text, h.hearing_date, r)} - found
            gains.append(1 if hit_rel else 0)
            found.update(hit_rel)
        recall20 = len(found) / len(rels) if rels else 0.0
        dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains[:10]))
        ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(rels))))
        ndcg10 = dcg / ideal if ideal else 0.0
        rows_out.append({"id": q["id"], "query": q["query"], "recall@20": round(recall20, 4), "ndcg@10": round(ndcg10, 4),
                         "latency_ms": round(ms, 1), "signals": resp.signal_counts})
    th = suite.get("thresholds", {"recall@20": 0.85, "ndcg@10": 0.6, "p95_latency_ms": 800})
    lat_sorted = sorted(lat)
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(round(0.95 * (len(lat_sorted) - 1))))] if lat_sorted else None
    summary = {
        "suite": suite.get("name", path.stem), "backend": backend.name, "queries": len(rows_out),
        "recall@20": round(statistics.mean(r["recall@20"] for r in rows_out), 4) if rows_out else None,
        "ndcg@10": round(statistics.mean(r["ndcg@10"] for r in rows_out), 4) if rows_out else None,
        "p50_latency_ms": round(statistics.median(lat), 1) if lat else None,
        "p95_latency_ms": round(p95, 1) if p95 is not None else None,
        "thresholds": th,
    }
    summary["meets_thresholds"] = bool(rows_out) and (summary["recall@20"] >= th["recall@20"] and summary["ndcg@10"] >= th["ndcg@10"]
                                                      and summary["p95_latency_ms"] <= th["p95_latency_ms"])
    summary["opensearch_recommended"] = not summary["meets_thresholds"]
    return {"summary": summary, "results": rows_out}


# ---------------------------------------------------------------------------
# human labelling
# ---------------------------------------------------------------------------
def _ordered(ids: list[str], seed: str) -> list[str]:
    return sorted(ids, key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).hexdigest())


def export_label_sample(engine: Engine, *, kind: str, n: int, out: Path, seed: str) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        if kind == "speakers":
            data = rows(conn, """SELECT su.id, h.hearing_date::text AS hearing_date, su.page_no, su.line_start, su.line_end,
                                        su.speaker_label, su.speaker_role, su.unit_type, su.raw_text
                                 FROM ntk.source_units su LEFT JOIN ntk.hearings h ON h.id = su.hearing_id
                                 WHERE su.unit_type <> 'caption'""")
            cols = ["id", "hearing_date", "page_no", "line_start", "line_end", "speaker_label", "speaker_role", "unit_type",
                    "text", "label_speaker_correct", "label_true_speaker", "label_location_correct", "label_notes"]
        elif kind == "exchanges":
            data = rows(conn, """SELECT x.id, h.hearing_date::text AS hearing_date, q.page_no, q.line_start, x.asker_label,
                                        a.page_no AS answer_page_no, a.line_start AS answer_line_start,
                                        x.witness_label, x.answer_relation::text AS answer_relation, q.raw_text AS question,
                                        a.raw_text AS answer
                                 FROM ntk.qa_exchanges x JOIN ntk.source_units q ON q.id = x.question_unit_id
                                 JOIN ntk.source_units a ON a.id = x.answer_unit_id JOIN ntk.hearings h ON h.id = x.hearing_id""")
            cols = ["id", "hearing_date", "page_no", "line_start", "answer_page_no", "answer_line_start", "asker_label",
                    "witness_label", "answer_relation", "question", "answer", "label_pair_correct", "label_relation_correct",
                    "label_notes"]
        else:
            data = rows(conn, """SELECT a.id AS answer_id, s.ord, s.sec->>'kind' AS kind, s.sec->>'text' AS assertion,
                                        cid AS source_unit_id, su.raw_text AS cited_text
                                 FROM ntk.answers a, LATERAL jsonb_array_elements(a.envelope->'sections') WITH ORDINALITY s(sec, ord),
                                      LATERAL jsonb_array_elements_text(s.sec->'citation_ids') cid
                                 JOIN ntk.source_units su ON su.id = cid
                                 WHERE a.answer_status IN ('answered','false_premise_corrected')""")
            for d in data:
                d["id"] = f"{d['answer_id']}:{d['ord']}:{d['source_unit_id']}"
            cols = ["id", "answer_id", "kind", "assertion", "source_unit_id", "cited_text", "label_supported", "label_notes"]
    by_id = {str(d["id"]): d for d in data}
    picked = _ordered(list(by_id), seed)[:n]
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i in picked:
            d = dict(by_id[i])
            d["text"] = d.get("raw_text", d.get("text"))
            for c in cols:
                d.setdefault(c, "")
            w.writerow(d)
    return len(picked)


def score_labels(*, kind: str, path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = list(csv.DictReader(fh))
    yes = {"y", "yes", "1", "true", "כן", "v"}
    no = {"n", "no", "0", "false", "לא", "x"}

    def rate(col: str) -> dict:
        labeled = [r for r in data if (r.get(col) or "").strip().lower() in yes | no]
        ok = sum(1 for r in labeled if r[col].strip().lower() in yes)
        return {"labeled": len(labeled), "correct": ok, "precision": round(ok / len(labeled), 4) if labeled else None}

    if kind == "speakers":
        r = rate("label_speaker_correct")
        loc = rate("label_location_correct")
        return {"metric": "speaker_precision", **r, "target": 0.97, "location_precision": loc,
                "passed": r["precision"] is not None and r["labeled"] >= 200 and r["precision"] >= 0.97}
    if kind == "exchanges":
        r = rate("label_pair_correct")
        rel = rate("label_relation_correct")
        return {"metric": "qa_pairing_precision", **r, "relation_precision": rel, "target": 0.95,
                "passed": r["precision"] is not None and r["labeled"] >= 100 and r["precision"] >= 0.95}
    r = rate("label_supported")
    return {"metric": "citation_precision", **r, "target": 0.95, "passed": r["precision"] is not None and r["precision"] >= 0.95}


# ---------------------------------------------------------------------------
# search-bench relevance labelling (pooling)
# ---------------------------------------------------------------------------
def export_search_pool(path: Path, *, services, out: Path, depth: int = 20) -> int:
    """Pool the top-`depth` hits of every signal separately and fused, so labels are not biased toward one ranker."""
    suite = json.loads(path.read_text(encoding="utf-8"))
    backend = services.search_backend()
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["query_id", "query", "source_unit_id", "hearing_date", "page", "line_start",
                                           "text", "label_relevant", "label_fragment"])
        w.writeheader()
        for q in suite["queries"]:
            pool: dict[str, Any] = {}
            for sig in (None, *SearchRequest(q["query"]).signals):
                req = SearchRequest(q["query"], SearchFilters(published_only=False), limit=depth,
                                    **({"signals": (sig,)} if sig else {}))
                for h in backend.search(req).hits:
                    pool.setdefault(h.source_unit_id, h)
            for h in sorted(pool.values(), key=lambda h: (h.hearing_date or "", h.page, h.line_start)):
                w.writerow({"query_id": q["id"], "query": q["query"], "source_unit_id": h.source_unit_id,
                            "hearing_date": h.hearing_date or "", "page": h.page, "line_start": h.line_start,
                            "text": h.text, "label_relevant": "", "label_fragment": ""})
                n += 1
    return n


def apply_search_labels(path: Path, labels: Path) -> dict[str, int]:
    """Write labelled relevance back into the suite: label_relevant=1 rows become {contains, hearing_date}."""
    suite = json.loads(path.read_text(encoding="utf-8"))
    rel: dict[str, list[dict]] = {}
    with labels.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("label_relevant", "").strip() in {"1", "y", "yes", "כן"}:
                frag = (r.get("label_fragment") or r["text"]).strip()[:160]
                rel.setdefault(r["query_id"], []).append({"contains": frag, "hearing_date": r["hearing_date"] or None})
    for q in suite["queries"]:
        q["relevant"] = rel.get(q["id"], [])
    suite["status"] = "labelled"
    path.write_text(json.dumps(suite, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"queries": len(suite["queries"]), "labelled_queries": sum(1 for q in suite["queries"] if q["relevant"])}


# ---------------------------------------------------------------------------
# server-side evaluation runs (admin API → worker)
# ---------------------------------------------------------------------------
GOLDEN_DIR = Path(__file__).resolve().parents[3] / "golden"


class SuiteNotFound(ValueError):
    pass


def resolve_suite(name: str, *, golden_dir: Path | None = None) -> Path:
    """Map a suite name ("search-bench-real-sept2025-v1" or "golden/….json") to a file inside golden/.

    Only top-level JSON files in golden/ are accepted, so the API can never be used to read other paths."""
    base = (golden_dir or GOLDEN_DIR).resolve()
    stem = Path(name).name
    if stem.endswith(".json"):
        stem = stem[:-5]
    if not stem or not all(c.isalnum() or c in "-_." for c in stem) or stem.startswith("."):
        raise SuiteNotFound(f"invalid suite name {name!r}")
    path = (base / f"{stem}.json").resolve()
    if path.parent != base or not path.is_file():
        raise SuiteNotFound(f"suite {stem!r} not found in golden/")
    return path


def run_evaluation(kind: str, suite: Path, *, settings, engine: Engine, services, options: dict | None = None) -> dict:
    options = options or {}
    if kind == "search_bench":
        return run_search_bench(suite, services=services, published_only=bool(options.get("published_only", False)))
    if kind == "ask_suite":
        return run_suite(suite, settings=settings, engine=engine, services=services, as_of=options.get("as_of"))
    raise ValueError(f"unknown evaluation kind {kind!r}")
