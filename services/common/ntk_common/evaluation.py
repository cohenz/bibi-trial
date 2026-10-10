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
def run_suite(path: Path, *, settings, engine: Engine, services, as_of: str | None = None) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    as_of_dt = dt.datetime.fromisoformat((as_of or suite.get("as_of") or dt.datetime.now(dt.UTC).isoformat()).replace("Z", "+00:00"))
    engine_ask = AskEngine(PgAskStore(engine, case_id=settings.case_id), services.search_backend(), services.runner,
                           AskConfig(answer_base=settings.answer_base, citation_base=settings.citation_base, env=settings.env,
                                     independent_verifier=not services.registry.single_family))
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
                                             sv.publication_state FROM ntk.source_units su JOIN ntk.source_versions sv
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
        results.append({"id": q["id"], "category": q.get("category"), "question": q["question"],
                        "status": env["answer_status"], "expected": q["expect_status"], "status_ok": status_ok,
                        "forbidden_phrases": forbidden, "citations": len(env["citations"]), "citation_failures": loc_fail,
                        "answer_short": env["answer_short"], "permalink": env["permalink"], "latency_ms": round(latency, 1),
                        "passed": status_ok and not forbidden and not loc_fail})
    fp = [r for r in results if r["category"] in {"false_premise", "ruling_attribution", "injection", "fill_in", "misattribution", "ignore_sources"}]
    answerable = [r for r in results if r["category"] == "answerable"]
    thresholds = suite.get("thresholds", {})
    summary = {
        "suite": suite.get("name", path.stem),
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
        for rank, h in enumerate(resp.hits, start=1):
            hit_rel = [i for i, r in enumerate(rels) if _relevant(h.text, h.hearing_date, r)]
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
                    "text", "label_speaker_correct", "label_true_speaker", "label_notes"]
        elif kind == "exchanges":
            data = rows(conn, """SELECT x.id, h.hearing_date::text AS hearing_date, q.page_no, q.line_start, x.asker_label,
                                        x.witness_label, x.answer_relation::text AS answer_relation, q.raw_text AS question,
                                        a.raw_text AS answer
                                 FROM ntk.qa_exchanges x JOIN ntk.source_units q ON q.id = x.question_unit_id
                                 JOIN ntk.source_units a ON a.id = x.answer_unit_id JOIN ntk.hearings h ON h.id = x.hearing_id""")
            cols = ["id", "hearing_date", "page_no", "line_start", "asker_label", "witness_label", "answer_relation",
                    "question", "answer", "label_pair_correct", "label_relation_correct", "label_notes"]
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
        return {"metric": "speaker_precision", **r, "target": 0.97, "passed": r["precision"] is not None and r["labeled"] >= 200 and r["precision"] >= 0.97}
    if kind == "exchanges":
        r = rate("label_pair_correct")
        rel = rate("label_relation_correct")
        return {"metric": "qa_pairing_precision", **r, "relation_precision": rel, "target": 0.95,
                "passed": r["precision"] is not None and r["labeled"] >= 100 and r["precision"] >= 0.95}
    r = rate("label_supported")
    return {"metric": "citation_precision", **r, "target": 0.95, "passed": r["precision"] is not None and r["precision"] >= 0.95}
