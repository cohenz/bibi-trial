"""Layer A (HearingDigest) and layer B (ClaimBundle) builders.

Both builders are pure with respect to storage: they take source facts,
call the ``ModelRunner`` (which validates model output against contracts and
records the run), assemble the layer contract, validate it, and run the
gates. Persistence is the caller's job. A contract failure never produces a
stored "valid" object: the builder returns ``payload=None`` with the errors.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import contracts, gates, ids
from .llm.runner import ModelRunner, ModelRunRecord, unknown_ids_check

SCHEMA_VERSION = "2.0"


@dataclass
class UnitView:
    """What layers need to know about a SourceUnit."""

    id: str
    source_version_id: str
    page: int
    line_start: int
    line_end: int
    speaker_label: str | None
    speaker_role: str | None
    unit_type: str
    text: str
    court_record_status: str = "unknown"
    published: bool = False
    hearing_id: str | None = None
    examination_phase: str = "unknown"
    judicial_level: str | None = None
    judicial_human_approved: bool = False

    def facts(self) -> gates.UnitFacts:
        return gates.UnitFacts(self.id, self.text, self.speaker_role, self.unit_type, self.published,
                               self.judicial_level, self.judicial_human_approved)


@dataclass
class ExchangeView:
    id: str
    question_unit_id: str
    answer_unit_id: str
    answer_relation: str
    confidence: float
    interpreted_proposition: str | None
    verified: bool = False


@dataclass
class BuildResult:
    payload: dict | None
    runs: list[ModelRunRecord] = field(default_factory=list)
    decision: gates.GateDecision | None = None
    errors: list[dict] = field(default_factory=list)
    artifact_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.payload is not None and self.decision is not None and self.decision.state != "rejected"


def citation_for(u: UnitView, base: str, quote: str | None = None) -> dict:
    return {
        "source_unit_id": u.id,
        "source_version_id": u.source_version_id,
        "page": u.page,
        "line_start": u.line_start,
        "line_end": u.line_end,
        "speaker": u.speaker_label,
        "quote": quote,
        "court_record_status": u.court_record_status,
        "permalink": f"{base}{u.id}",
    }


def _now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


# =============================================================================
# Layer A
# =============================================================================

def build_hearing_digest(
    *, hearing_id: str, units: list[UnitView], exchanges: list[ExchangeView], runner: ModelRunner,
    corpus_version: str, citation_base: str, env: str, max_units: int = 400,
) -> BuildResult:
    by_id = {u.id: u for u in units}
    sample = [u for u in units if u.unit_type != "caption"][:max_units]
    payload_in = {
        "hearing_id": hearing_id,
        "units": [
            {"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role, "unit_type": u.unit_type,
             "phase": u.examination_phase, "page": u.page, "text": u.text[:2000]}
            for u in sample
        ],
        "exchanges": [
            {"id": e.id, "question_unit_id": e.question_unit_id, "answer_unit_id": e.answer_unit_id,
             "answer_relation": e.answer_relation}
            for e in exchanges
        ],
    }
    allowed_units = {u["id"] for u in payload_in["units"]}
    allowed_ex = {e.id for e in exchanges}

    def semantic(out: dict) -> list[dict]:
        # citations must be exact; judicial_candidate_unit_ids is a high-recall candidate list (not cited), so an
        # unknown id there is dropped below instead of discarding the whole digest
        errs = unknown_ids_check(allowed_units, "summary_sentences[].source_unit_ids[]")(out)
        errs += unknown_ids_check(allowed_ex, "notable_exchange_ids[]")(out)
        return errs

    run = runner.run("digest", payload_in, input_source_ids=sorted(allowed_units), corpus_version=corpus_version,
                     semantic_check=semantic)
    if not run.ok:
        return BuildResult(None, [run], None, run.validation_errors or [run.error or {}])

    out = run.output
    ex_by_id = {e.id: e for e in exchanges}
    cited_ids: list[str] = []
    for s in out["summary_sentences"]:
        for cid in s["source_unit_ids"]:
            if cid not in cited_ids:
                cited_ids.append(cid)
    notable = []
    for xid in out.get("notable_exchange_ids", []):
        e = ex_by_id[xid]
        notable.append({"question_unit_id": e.question_unit_id, "answer_unit_id": e.answer_unit_id,
                        "answer_relation": e.answer_relation, "interpreted_proposition": e.interpreted_proposition,
                        "confidence": float(e.confidence)})
        for cid in (e.question_unit_id, e.answer_unit_id):
            if cid not in cited_ids and cid in by_id:
                cited_ids.append(cid)
    summary = " ".join(s["text"] for s in out["summary_sentences"])
    digest_id = str(ids.derived_uuid("hearing_digest", hearing_id, run.id))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "id": digest_id,
        "hearing_id": hearing_id,
        "summary": summary,
        "summary_sentences": [{"text": s["text"], "citation_ids": s["source_unit_ids"]} for s in out["summary_sentences"]],
        "topics": list(dict.fromkeys(out.get("topics", []))),
        "persons": list(dict.fromkeys(out.get("persons", []))),
        "notable_exchanges": notable,
        "judicial_candidates": [u for u in dict.fromkeys(out.get("judicial_candidate_unit_ids", [])) if u in allowed_units],
        "citations": [citation_for(by_id[c], citation_base) for c in cited_ids if c in by_id],
        "review": {"state": "draft", "risk_flags": [], "reviewer": None, "reviewed_at": None},
    }
    try:
        contracts.validate("HearingDigest", payload)
    except contracts.ContractError as ce:
        return BuildResult(None, [run], None, ce.errors)

    facts = {u.id: u.facts() for u in units}
    assertions = [gates.Assertion(f"summary_sentences/{i}", s["text"], s["citation_ids"])
                  for i, s in enumerate(payload["summary_sentences"])]
    flags = sorted({f for a in assertions for f in gates.risk_flags(a.text)})
    results = [
        gates.citation_gate(assertions, facts, require_published=False),
        gates.support_gate(assertions, facts),
        gates.judicial_wording_gate(assertions, facts),
        gates.absolute_wording_gate(assertions, status=None),
        gates.provenance_gate([run.model_family], env=env),
    ]
    decision = gates.decide(results, flags=flags)
    payload["review"]["state"] = decision.state
    payload["review"]["risk_flags"] = decision.risk_flags
    contracts.validate("HearingDigest", payload)
    return BuildResult(payload, [run], decision, [], digest_id)


# =============================================================================
# Layer B
# =============================================================================

@dataclass
class ClaimView:
    id: str
    version_id: str
    question: str
    claim_text: str
    claim_type: str
    status: str = "unverified"
    sensitivity: list[str] = field(default_factory=list)
    disclosure: str | None = None


def _bucket(direction: str) -> str:
    return {"supports": "support", "weakens": "weakness"}.get(direction, "context")


def build_claim_bundle(
    *, claim: ClaimView, candidates: list[UnitView], exchanges_by_unit: dict[str, ExchangeView],
    runner: ModelRunner, corpus_version: str, citation_base: str, env: str, independent_verifier: bool,
    as_of: str | None = None,
) -> BuildResult:
    by_id = {u.id: u for u in candidates}
    cand_payload = []
    for u in candidates:
        ex = exchanges_by_unit.get(u.id)
        paired = None
        if ex is not None:
            paired = ex.answer_unit_id if ex.question_unit_id == u.id else ex.question_unit_id
        cand_payload.append({
            "id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role, "unit_type": u.unit_type,
            "phase": u.examination_phase, "text": u.text[:2000], "court_record_status": u.court_record_status,
            "exchange_id": ex.id if ex else None, "answer_relation": ex.answer_relation if ex else None,
            "paired_unit_id": paired if paired in by_id else None,
        })
    allowed = set(by_id)
    allowed_ex = {e.id for e in exchanges_by_unit.values()}

    def semantic(out: dict) -> list[dict]:
        errs = unknown_ids_check(allowed, "evidence[].source_unit_ids[]")(out)
        errs += unknown_ids_check(allowed_ex, "evidence[].exchange_id")(out)
        if out.get("claim_id") != claim.id:
            errs.append({"path": "/claim_id", "message": "claim_id mismatch", "validator": "semantic"})
        return errs

    map_run = runner.run("map_claim", {"claim_id": claim.id, "question": claim.question, "claim_text": claim.claim_text,
                                       "candidates": cand_payload},
                         input_source_ids=sorted(allowed), corpus_version=corpus_version, semantic_check=semantic)
    runs = [map_run]
    if not map_run.ok:
        return BuildResult(None, runs, None, map_run.validation_errors or [map_run.error or {}])

    # judicial classification of bench units among candidates (strong model only)
    judicial_candidates = [u for u in candidates if u.speaker_role in {"judge", "court"} or u.unit_type == "decision"]
    jlevels: dict[str, dict] = {}
    if judicial_candidates:
        jrun = runner.run("judicial", {"candidates": [
            {"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role, "unit_type": u.unit_type,
             "text": u.text[:2000]} for u in judicial_candidates]},
            input_source_ids=[u.id for u in judicial_candidates], corpus_version=corpus_version,
            semantic_check=unknown_ids_check({u.id for u in judicial_candidates}, "classifications[].source_unit_id"))
        runs.append(jrun)
        if jrun.ok:
            for c in jrun.output["classifications"]:
                if c["is_judicial"] and c.get("level"):
                    jlevels[c["source_unit_id"]] = c

    support, weakness, context_points = [], [], []
    evidence_assertions: list[gates.Assertion] = []
    cited: list[str] = []
    for i, ev in enumerate(map_run.output["evidence"]):
        evid = str(ids.derived_uuid("evidence", claim.id, *ev["source_unit_ids"], ev["attribution"]))
        units_for = [by_id[x] for x in ev["source_unit_ids"]]
        crs = _strongest_record_status([u.court_record_status for u in units_for])
        point = {"evidence_id": evid, "summary": ev["summary"], "direction": ev["direction"],
                 "court_record_status": crs, "citation_ids": ev["source_unit_ids"]}
        b = _bucket(ev["direction"])
        (support if b == "support" else weakness if b == "weakness" else context_points).append(point)
        evidence_assertions.append(gates.Assertion(f"evidence/{i}", ev["summary"], ev["source_unit_ids"],
                                                   attribution=ev["attribution"], exchange_id=ev.get("exchange_id")))
        for x in ev["source_unit_ids"]:
            if x not in cited:
                cited.append(x)

    court_position = None
    ranked = sorted(jlevels.values(), key=lambda c: ["question_or_comment", "interim_observation",
                                                    "procedural_decision", "substantive_ruling"].index(c["level"]), reverse=True)
    if ranked:
        top = ranked[0]
        court_position = {"level": top["level"], "summary": top.get("summary") or by_id[top["source_unit_id"]].text[:200],
                          "citation_ids": [top["source_unit_id"]]}
        if top["source_unit_id"] not in cited:
            cited.append(top["source_unit_id"])

    if not cited:
        return BuildResult(None, runs, None, [{"path": "/citations", "message": "no evidence found for claim", "validator": "minItems"}])

    status = claim.status
    if status == "unverified" and support:
        status = "source_backed"
    if weakness and support and status in {"unverified", "source_backed"}:
        status = "disputed"
    answer_short = _answer_short(len(support), len(weakness), court_position)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "claim_id": claim.id,
        "claim_version_id": claim.version_id,
        "question": claim.question,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "status": status,
        "as_of": as_of or _now(),
        "answer_short": answer_short,
        "support": support,
        "weakness": weakness,
        "court_position": court_position,
        "unresolved_questions": map_run.output.get("unresolved_questions", []),
        "citations": [citation_for(by_id[c], citation_base) for c in cited],
        "review": {"state": "draft", "risk_flags": [], "reviewer": None, "reviewed_at": None},
        "disclosure": claim.disclosure,
    }
    try:
        contracts.validate("ClaimBundle", payload)
    except contracts.ContractError as ce:
        return BuildResult(None, runs, None, ce.errors)

    # independent verification
    assertions = list(evidence_assertions)
    if court_position:
        assertions.append(gates.Assertion("court_position", court_position["summary"], court_position["citation_ids"],
                                          attribution="judge_commented" if court_position["level"] in
                                          {"question_or_comment", "interim_observation"} else "court_decided"))
    vrun = runner.run("verify", {
        "assertions": [{"path": a.path, "text": a.text, "citation_ids": a.citation_ids} for a in assertions],
        "sources": [{"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role, "text": u.text[:2000],
                     "judicial_level": (jlevels.get(u.id) or {}).get("level")} for u in candidates],
    }, input_source_ids=sorted(allowed), corpus_version=corpus_version,
        semantic_check=None)
    runs.append(vrun)
    verdict = vrun.output.get("verdict") if vrun.ok else None

    facts = {u.id: u.facts() for u in candidates}
    flags = set(claim.sensitivity)
    for a in assertions:
        flags.update(gates.risk_flags(a.text))
    flags.update(gates.risk_flags(claim.claim_text))
    if jlevels:
        flags.add("judicial_classification")  # spec §16.5: always human-reviewed
    verified_affirmations = {e.id for e in exchanges_by_unit.values() if e.verified and e.answer_relation == "affirms"}
    sensitive = bool(flags)
    results = [
        gates.citation_gate(assertions, facts, require_published=False),
        gates.support_gate(assertions, facts),
        gates.attribution_gate(assertions, facts, verified_affirmations),
        gates.judicial_wording_gate(assertions, facts),
        gates.absolute_wording_gate(assertions, status=status),
        gates.counterevidence_gate(available_weakening=sum(1 for e in map_run.output["evidence"] if e["direction"] == "weakens"),
                                   included_weakening=len(weakness)),
        gates.verifier_gate(verdict, independent_family=independent_verifier, sensitive=sensitive),
        gates.provenance_gate([r.model_family for r in runs], env=env),
    ]
    decision = gates.decide(results, flags=flags)
    payload["review"]["state"] = decision.state
    payload["review"]["risk_flags"] = decision.risk_flags
    contracts.validate("ClaimBundle", payload)
    artifact_id = str(ids.derived_uuid("claim_card", claim.id, claim.version_id, ids.sha256_json(payload["citations"]), map_run.id))
    return BuildResult(payload, runs, decision, [], artifact_id)


def _strongest_record_status(values: list[str]) -> str:
    order = ["admitted", "filed", "marked_for_identification", "referenced_in_court", "excluded", "not_filed", "external", "unknown"]
    for v in order:
        if v in values:
            return v
    return "unknown"


def _answer_short(n_support: int, n_weak: int, court: dict | None) -> str:
    parts = [f"בחומר שמופה נמצאו {n_support} פריטים המחזקים את הטענה ו־{n_weak} פריטים המחלישים אותה."]
    if court:
        level_he = {"question_or_comment": "שאלה או הערה של שופט", "interim_observation": "הערת ביניים של ההרכב",
                    "procedural_decision": "החלטה דיונית", "substantive_ruling": "הכרעה מהותית"}[court["level"]]
        parts.append(f"בחומר יש {level_he} הנוגעת לנושא.")
    else:
        parts.append("לא נמצאה בחומר שמופה עמדה של בית המשפט בנושא.")
    return " ".join(parts)
