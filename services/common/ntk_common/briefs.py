"""Document briefs (11.10.2026): for every non-protocol document — a title that says what it is about, one to three
cited sentences, a significance verdict (substantive / procedural) and, for court notices that record a hearing day,
who testified and when.

Like the hearing digests, briefs pass the gates and the verifier and are published automatically when clean
(ADR-0014). Party documents (motions, responses, notices) must attribute positions; only a court-issued document may
say what the court decided, and only by citing its own units.
"""

from __future__ import annotations

import re

from . import contracts, gates, ids
from .guides import allegation_framing_gate, name_matches
from .layers import SCHEMA_VERSION, BuildResult, UnitView, _semantic_support_check, citation_for
from .llm.runner import ModelRunner

COURT_TYPES = {"decision"}
MAX_UNITS = 400


def _court_wording_gate(asserts: list[gates.Assertion], by_id: dict[str, UnitView], court_doc: bool) -> gates.GateResult:
    """'בית המשפט החליט…' is allowed only in a court document and only when every cited unit is the court's own text."""
    details = []
    for a in asserts:
        hits = gates.find_determination_language(a.text)
        if not hits:
            continue
        ok = court_doc and a.citation_ids and all(
            (u := by_id.get(c)) is not None and (u.unit_type == "decision" or u.speaker_role == "court") for c in a.citation_ids)
        if not ok:
            details.append({"path": a.path, "problem": "determination_wording_without_court_text", "phrases": hits})
    return gates.GateResult("judicial_wording", not details, "error", details)


def _witness_gate(days: list[dict], by_id: dict[str, UnitView]) -> gates.GateResult:
    """Every witness named for a hearing day must appear in the units cited for that day."""
    details = []
    for i, d in enumerate(days):
        text = "\n".join(by_id[c].text for c in d["citation_ids"] if c in by_id)
        for w in d["witnesses"]:
            if not name_matches(w["name"], text):
                details.append({"path": f"hearing_days/{i}", "problem": "witness_not_in_cited_text", "name": w["name"]})
    return gates.GateResult("witness_names", not details, "error", details)


def _valid_date(d: str | None) -> str | None:
    """ISO date from what the model wrote: '2026-04-20', '20.4.2026', '20/04/2026', '28 אפריל 2026'."""
    from .pipeline.protocol import parse_date

    if not d:
        return None
    d = d.strip()
    iso = d if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else parse_date(d.replace("/", "."))
    return iso if iso and "2016-01-01" <= iso <= "2035-12-31" else None


def build_document_brief(*, source_version_id: str, source_type: str, units: list[UnitView], runner: ModelRunner,
                         corpus_version: str, citation_base: str, env: str, archive_title: str | None = None) -> BuildResult:
    sample = [u for u in units if (u.text or "").strip()][:MAX_UNITS]
    by_id = {u.id: u for u in sample}
    allowed = set(by_id)
    payload_in = {
        "document_source_type": source_type,
        "archive_title": archive_title,
        "units": [{"id": u.id, "page": u.page, "speaker": u.speaker_label, "unit_type": u.unit_type, "text": u.text[:1500]}
                  for u in sample],
    }
    run = runner.run("document_brief", payload_in, input_source_ids=sorted(allowed), corpus_version=corpus_version)
    if not run.ok:
        return BuildResult(None, [run], None, run.validation_errors or [run.error or {}])
    out = run.output

    def keep(xs: list[str]) -> list[str]:
        return [x for x in dict.fromkeys(xs) if x in allowed]

    title_ids = keep(out["title"]["source_unit_ids"])
    summary = [{"text": s["text"].strip(), "citation_ids": c} for s in out["summary"] if (c := keep(s["source_unit_ids"]))]
    days = []
    for d in out.get("hearing_days") or []:
        hd, c = _valid_date(d["hearing_date"]), keep(d["source_unit_ids"])
        if hd and c:
            days.append({"hearing_date": hd, "witnesses": [w for w in d["witnesses"] if w.get("name", "").strip()],
                         "next_hearing_date": _valid_date(d.get("next_hearing_date")), "citation_ids": c})
    if not title_ids or not summary:
        return BuildResult(None, [run], None, [{"path": "/title", "message": "no cited title or summary", "validator": "minItems"}])
    brief_id = str(ids.derived_uuid("document_brief", source_version_id, run.id))
    cited = list(dict.fromkeys(title_ids + [c for s in summary for c in s["citation_ids"]] + [c for d in days for c in d["citation_ids"]]))
    payload = {
        "schema_version": SCHEMA_VERSION, "id": brief_id, "source_version_id": source_version_id, "source_type": source_type,
        "title": {"text": out["title"]["text"].strip(), "citation_ids": title_ids},
        "summary_sentences": summary, "significance": out["significance"],
        "significance_reason": out.get("significance_reason"), "hearing_days": days,
        "citations": [citation_for(by_id[c], citation_base) for c in cited],
        "review": {"state": "draft", "risk_flags": [], "reviewer": None, "reviewed_at": None},
    }
    try:
        contracts.validate("DocumentBrief", payload)
    except contracts.ContractError as ce:
        return BuildResult(None, [run], None, ce.errors)

    court_doc = source_type in COURT_TYPES
    # paths: summary_sentences/0 is the title, /1… the summary (the verifier escalation reads sentences by index)
    asserts = [gates.Assertion("summary_sentences/0", payload["title"]["text"], title_ids)] + [
        gates.Assertion(f"summary_sentences/{i + 1}", s["text"], s["citation_ids"]) for i, s in enumerate(summary)]
    facts = {u.id: u.facts() for u in sample}
    flags = sorted({f for a in asserts for f in gates.risk_flags(a.text)} - ({"court_determined_wording"} if court_doc else set()))
    results = [
        gates.citation_gate(asserts, facts, require_published=False),
        gates.support_gate(asserts, facts),
        _court_wording_gate(asserts, by_id, court_doc),
        gates.absolute_wording_gate(asserts, status=None),
        _witness_gate(days, by_id),
        gates.provenance_gate([run.model_family], env=env),
    ]
    if not court_doc:
        results.append(allegation_framing_gate(asserts))
    decision = gates.decide(results, flags=flags)
    payload["review"]["state"] = decision.state
    payload["review"]["risk_flags"] = decision.risk_flags
    res = BuildResult(payload, [run], decision, [], brief_id)
    if decision.state == "human_review_required":
        # the lexical floor is cheap; let the verifier confirm sentences it flags (same as hearing digests)
        shim = {"summary_sentences": [{"text": a.text, "citation_ids": a.citation_ids} for a in asserts], "review": {}}
        shadow = BuildResult(shim, res.runs, decision, [], brief_id)
        _semantic_support_check(shadow, runner=runner, by_id=by_id, corpus_version=corpus_version)
        res.runs = shadow.runs
        if shadow.decision is not None and shadow.decision is not decision:
            res.decision = shadow.decision
            payload["review"]["state"] = shadow.decision.state
    return res
