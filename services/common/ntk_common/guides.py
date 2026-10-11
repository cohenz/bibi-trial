"""Reader guides (ADR-0015): entry points built over the record.

* ``indictment``/``main`` — what the indictment is about and who is charged;
* ``case``/``1000|2000|4000`` — one guide per count: the story the indictment alleges, people, charges, dated events;
* ``witness``/``w_<hex>`` — who the witness is and what they said in court.

Builders are pure like ``layers``: they call the ``ModelRunner``, keep only ids that exist in the input, assemble a
``GuideObject``, and run the gates plus the verifier. Every guide ends in ``human_review_required`` (or ``rejected``):
these are the most read pages of the site and a person approves each one once.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import contracts, gates, hebrew, ids
from .layers import SCHEMA_VERSION, BuildResult, UnitView, _complete_citations, citation_for
from .llm.runner import ModelRunner, ModelRunRecord

CASE_KEYS = ("4000", "2000", "1000")
CASE_TITLES = {k: f"תיק {k}" for k in CASE_KEYS}
_ORDINALS = {"ראשון": 1, "שני": 2, "שלישי": 3, "רביעי": 4}

# --- allegation framing ---------------------------------------------------------------------------------------------
# A sentence drawn from the indictment that states an offense as a plain fact is rejected and the model retries.
_FRAMING = re.compile(r"כתב\s*ה?אישום|נטען|נטענ|לטענת|מייחס|מיוחס|מואשמ|מואשם|יוחס|המאשימה|התביעה|כביכול|לכאורה|על\s*פי\s*האישום")
_GUILT = [r"(?:^|\s)אשם(?:\s|$)", r"(?:^|\s)הורשע", r"ביצע\s*(?:את\s*)?(?:ה)?עביר", r"(?:לקח|קיבל|נתן)\s*שוחד",
          r"(?:^|\s)שיחד(?:\s|$)", r"(?:^|\s)הוכח"]


def find_unframed_guilt(text: str) -> list[str]:
    t = hebrew.normalize(text)
    if _FRAMING.search(t):
        return []
    return [m.group(0).strip() for p in _GUILT for m in re.finditer(p, t)]


def allegation_framing_gate(assertions: list[gates.Assertion]) -> gates.GateResult:
    details = []
    for a in assertions:
        hits = find_unframed_guilt(a.text)
        if hits:
            details.append({"path": a.path, "problem": "allegation_stated_as_fact", "phrases": hits})
    return gates.GateResult("allegation_framing", not details, "error", details)


# --- indictment structure -------------------------------------------------------------------------------------------
_COUNT_HEAD = re.compile(r"^\s*האישום\s+ה?(ראשון|שני|שלישי|רביעי)\b(.{0,80})")
_CASE_NO = re.compile(r"(?<!\d)(1000|2000|4000)(?!\d)")


@dataclass
class IndictmentParts:
    general: list[UnitView] = field(default_factory=list)
    summary: list[UnitView] = field(default_factory=list)
    counts: dict[str, list[UnitView]] = field(default_factory=dict)  # case key → units of the count
    appendices: dict[str, list[UnitView]] = field(default_factory=dict)  # case key → appendix units
    count_order: list[str] = field(default_factory=list)


def _uniq(units: list[UnitView]) -> list[UnitView]:
    seen: set[str] = set()
    out = []
    for u in units:
        if u.id not in seen:
            seen.add(u.id)
            out.append(u)
    return out


def _first_line(u: UnitView) -> str:
    return (u.text or "").strip().split("\n", 1)[0].strip()


def _heading(line: str) -> tuple[str, str | None] | None:
    """('general'|'summary'|'count'|'stop'|'appendix', detail) for a section heading line, else None."""
    line = line.strip()
    m = _COUNT_HEAD.match(line)
    if line.startswith("חלק כללי"):
        return "general", None
    if line.startswith("תמצית האישום"):
        return "summary", None
    if m and _CASE_NO.search(m.group(2)):
        return "count", _CASE_NO.search(m.group(2)).group(1)  # type: ignore[union-attr]
    if line.startswith(("עדי התביעה", "רשימת עדי", "הודעה לבית המשפט", "הודעה לנאשמים", "בקשת חילוט")):
        return "stop", None
    if line.startswith("נספח") and len(line) < 120:
        letter = line.split()[1] if len(line.split()) > 1 else ""
        return "appendix", letter.strip("'׳–- ")
    return None


def split_indictment(units: list[UnitView]) -> IndictmentParts:
    """Sections by their printed headings: the general part, the summary ('תמצית האישום…'), each count ('האישום הראשון –
    פרשת 4000 …') up to the witness list, and appendices ('נספח א'…') attached to the count that refers to them.
    A unit belongs to the section in force at its first line; a heading inside a unit starts a section for the next
    units (paragraph splitting sometimes glues a heading to the paragraph before it)."""
    parts = IndictmentParts()
    section: str | None = "pre"
    appendix: tuple[str, list[UnitView]] | None = None
    appendices_raw: list[tuple[str, list[UnitView]]] = []

    def enter(h: tuple[str, str | None]) -> None:
        nonlocal section, appendix
        kind, detail = h
        if kind == "general":
            if section == "pre":
                section = "general"
        elif kind == "summary":
            section = "summary"
        elif kind == "count" and detail:
            section = detail
            parts.counts.setdefault(detail, [])
            if detail not in parts.count_order:
                parts.count_order.append(detail)
        elif kind == "stop":
            section = None
        elif kind == "appendix":
            appendix = (detail or "", [])
            appendices_raw.append(appendix)
            section = "appendix"

    for u in units:
        lines = [ln for ln in (u.text or "").strip().split("\n") if ln.strip()]
        if lines and (h := _heading(lines[0])):
            enter(h)
        if section == "general":
            parts.general.append(u)
        elif section == "summary":
            parts.summary.append(u)
        elif section in parts.counts:
            parts.counts[section].append(u)
        elif section == "appendix" and appendix is not None:
            appendix[1].append(u)
        for ln in lines[1:]:
            if h := _heading(ln):
                enter(h)
    for letter, aunits in appendices_raw:
        ref = re.compile(rf"נספח\s*[\"״'׳]?\s*{re.escape(letter)}(?![א-ת])")
        owner = next((k for k in parts.count_order if any(ref.search(x.text) for x in parts.counts[k])), None)
        if owner is None:  # fall back to the case number written in the appendix itself
            hit = _CASE_NO.search(" ".join(x.text for x in aunits[:3]))
            owner = hit.group(1) if hit else None
        if owner:
            parts.appendices.setdefault(owner, []).extend(aunits)
    return parts


# --- witnesses ------------------------------------------------------------------------------------------------------
_DEFENDANT_PREFIX = re.compile(r"^\s*(נאש[םמ]ת?\s*\d+)\s*[—–-]\s*")


def witness_name(raw: str) -> tuple[str, str | None]:
    """'נאשם 1 — בנימין נתניהו' → ('בנימין נתניהו', 'נאשם 1')."""
    m = _DEFENDANT_PREFIX.match(raw or "")
    if m:
        return raw[m.end():].strip(), m.group(1).strip()
    return (raw or "").strip(), None


def witness_slug(name: str) -> str:
    folded = re.sub(r"\s+", " ", hebrew.normalize(name)).strip()
    return "w_" + hashlib.sha1(folded.encode("utf-8")).hexdigest()[:10]


def name_matches(name: str, text: str) -> bool:
    """A person is mentioned when their family name appears (with their first name if it is in the text)."""
    parts = [p for p in re.split(r"\s+", hebrew.normalize(name).replace("'", "").replace("׳", "")) if len(p) > 1]
    if not parts:
        return False
    t = hebrew.normalize(text).replace("'", "").replace("׳", "")
    return re.search(rf"(?<![א-ת]){re.escape(parts[-1])}(?![א-ת])", t) is not None


# --- builders -------------------------------------------------------------------------------------------------------
def _unit_payload(units: list[UnitView], chars: int) -> list[dict]:
    return [{"id": u.id, "page": u.page, "speaker": u.speaker_label, "speaker_role": u.speaker_role,
             "unit_type": u.unit_type, "phase": u.examination_phase, "text": (u.text or "")[:chars]} for u in units]


def _keep_ids(ids_: list[str], allowed: set[str]) -> list[str]:
    return [i for i in dict.fromkeys(ids_) if i in allowed]


def _item(text: str, cids: list[str], **extra) -> dict:
    d = {"label": None, "text": text.strip(), "date": None, "date_precision": None, "case_keys": [], "witness_slug": None,
         "citation_ids": cids}
    d.update(extra)
    return d


def _norm_date(d: str, precision: str) -> tuple[str, str] | None:
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", d or "")
    if not m:
        return None
    y, mo, da = m.group(1), m.group(2), m.group(3)
    if not 2000 <= int(y) <= 2035:
        return None
    if da and precision == "day":
        return f"{y}-{mo}-{da}", "day"
    if mo and precision in {"day", "month"}:
        return f"{y}-{mo}-01", "month"
    return f"{y}-01-01", "year"


def _assertions(payload: dict) -> list[gates.Assertion]:
    out = []
    for bi, b in enumerate(payload["blocks"]):
        for ii, it in enumerate(b["items"]):
            text = f"{it['label']}: {it['text']}" if it.get("label") and b["block"] in {"events"} else it["text"]
            out.append(gates.Assertion(f"blocks/{bi}/items/{ii}", text, it["citation_ids"]))
    return out


def _citations(payload: dict, by_id: dict[str, UnitView], base: str) -> None:
    seen: list[str] = []
    for b in payload["blocks"]:
        for it in b["items"]:
            for c in it["citation_ids"]:
                if c not in seen and c in by_id:
                    seen.append(c)
    payload["citations"] = [citation_for(by_id[c], base) for c in seen]


def _decide(payload: dict, units: list[UnitView], runner: ModelRunner, runs: list[ModelRunRecord], *, corpus_version: str,
            env: str, allegation: bool, citation_base: str) -> gates.GateDecision:
    """Gates, then the verifier over every item. The result is never machine-publishable on its own."""
    by_id = {u.id: u for u in units}
    facts = {u.id: u.facts() for u in units}

    def run_gates() -> tuple[list[gates.GateResult], list[str], list[gates.Assertion]]:
        asserts = _assertions(payload)
        flags = sorted({f for a in asserts for f in gates.risk_flags(a.text)} - {"final_legal_conclusion"} if allegation
                       else {f for a in asserts for f in gates.risk_flags(a.text)})
        res = [
            gates.citation_gate(asserts, facts, require_published=False),
            gates.support_gate(asserts, facts, min_overlap=0.15),
            gates.judicial_wording_gate(asserts, facts),
            gates.absolute_wording_gate(asserts, status=None),
            gates.provenance_gate([r.model_family for r in runs], env=env),
        ]
        if allegation:
            res.append(allegation_framing_gate(asserts))
        return res, flags, asserts

    results, flags, asserts = run_gates()
    decision = gates.decide(results, flags=flags, force_human=True)
    if decision.state == "human_review_required":
        # sentence-level citations are often incomplete (a name or a date sits in a neighbouring paragraph)
        flat = {"summary_sentences": [{"text": a.text, "citation_ids": a.citation_ids} for a in asserts], "citations": []}
        idx = {a.path: i for i, a in enumerate(asserts)}
        sup = next(r for r in results if r.gate == "support")
        as_digest = gates.GateDecision(decision.state, [gates.GateResult(
            "support", sup.passed, sup.severity,
            [{**d, "path": f"summary_sentences/{idx[d['path']]}"} for d in sup.details if d.get("path") in idx])], [])
        if _complete_citations(flat, as_digest, units, by_id, citation_base, window=12, max_extra=2):
            i = 0
            for b in payload["blocks"]:
                for it in b["items"]:
                    it["citation_ids"] = flat["summary_sentences"][i]["citation_ids"]
                    i += 1
            results, flags, asserts = run_gates()
            decision = gates.decide(results, flags=flags, force_human=True)
    if decision.state == "rejected":
        return decision
    cited = {c for a in asserts for c in a.citation_ids if c in by_id}
    vrun = runner.run("verify", {"assertions": [{"path": a.path, "text": a.text, "citation_ids": a.citation_ids} for a in asserts],
                                 "sources": [{"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role,
                                              "text": (u.text or "")[:2000], "judicial_level": None}
                                             for u in units if u.id in cited]},
                      input_source_ids=sorted(cited), corpus_version=corpus_version)
    runs.append(vrun)
    verdicts = {a["path"]: a for a in (vrun.output.get("assertions", []) if vrun.ok else [])}
    not_confirmed = [p for p in (a.path for a in asserts)
                     if not ((v := verdicts.get(p)) and v.get("supported") == "yes" and v.get("attribution_ok", False)
                             and not v.get("judicial_overstatement") and not v.get("false_premise"))]
    results.append(gates.GateResult("verifier", vrun.ok and not not_confirmed, "review",
                                    [] if vrun.ok and not not_confirmed else
                                    [{"problem": "verifier_not_confirmed" if vrun.ok else "not_verified",
                                      "paths": not_confirmed[:50], "verifier_run_id": vrun.id}]))
    return gates.decide(results, flags=flags, force_human=True)


def _finish(payload: dict, units: list[UnitView], runner: ModelRunner, runs: list[ModelRunRecord], *, corpus_version: str,
            env: str, allegation: bool, citation_base: str) -> BuildResult:
    payload["blocks"] = [b for b in payload["blocks"] if b["items"]]
    by_id = {u.id: u for u in units}
    decision = _decide(payload, units, runner, runs, corpus_version=corpus_version, env=env, allegation=allegation,
                       citation_base=citation_base)
    _citations(payload, by_id, citation_base)
    payload["review"] = {"state": decision.state, "risk_flags": decision.risk_flags, "reviewer": None, "reviewed_at": None}
    try:
        contracts.validate("GuideObject", payload)
    except contracts.ContractError as ce:
        return BuildResult(None, runs, None, ce.errors)
    return BuildResult(payload, runs, decision, [], payload["id"])


def _run_with_framing_retry(task: str, payload_in: dict, *, runner: ModelRunner, allowed: set[str], corpus_version: str,
                            assemble, units: list[UnitView], env: str, allegation: bool, citation_base: str) -> BuildResult:
    runs: list[ModelRunRecord] = []
    avoid: list[str] = []
    result: BuildResult | None = None
    for _ in range(2):
        p = dict(payload_in)
        if avoid:
            p["wording_rules"] = {
                "previous_draft_rejected_for": "an allegation or a court decision written as an established fact",
                "do_not_use": sorted(set(avoid)),
                "instead": "attribute every such sentence: 'לפי כתב האישום…', 'כתב האישום מייחס ל…', 'נטען כי…'",
            }
        run = runner.run(task, p, input_source_ids=sorted(allowed), corpus_version=corpus_version)
        runs.append(run)
        if not run.ok:
            return BuildResult(None, runs, None, run.validation_errors or [run.error or {}])
        payload = assemble(run)
        result = _finish(payload, units, runner, runs, corpus_version=corpus_version, env=env, allegation=allegation,
                         citation_base=citation_base)
        result.runs = runs
        if result.decision is None or result.decision.state != "rejected":
            return result
        failed = [r for r in result.decision.results if not r.passed and r.gate in {"allegation_framing", "judicial_wording",
                                                                                     "absolute_wording"}]
        if not failed:
            return result
        avoid += [ph for r in failed for d in r.details for ph in d.get("phrases", [])]
    return result  # type: ignore[return-value]


def build_indictment_overview(*, parts: IndictmentParts, source_version_id: str, runner: ModelRunner, corpus_version: str,
                              citation_base: str, env: str) -> BuildResult:
    charge_tails = []
    for k in parts.count_order:
        cu = parts.counts[k]
        idx = next((i for i, u in enumerate(cu) if "הוראות החיקוק" in (u.text or "")), None)
        charge_tails += [cu[0]] + (cu[idx: idx + 8] if idx is not None else cu[-6:])
    units = _uniq(parts.general + parts.summary + charge_tails)
    allowed = {u.id for u in units}

    def assemble(run: ModelRunRecord) -> dict:
        out = run.output
        overview = [_item(s["text"], c) for s in out["overview"] if (c := _keep_ids(s["source_unit_ids"], allowed))]
        defendants = [_item(d["text"], c, label=d["name"], case_keys=[k for k in d.get("case_keys", []) if k in CASE_KEYS])
                      for d in out["defendants"] if (c := _keep_ids(d["source_unit_ids"], allowed))]
        return {"schema_version": SCHEMA_VERSION, "id": str(ids.derived_uuid("guide", "indictment", "main", run.id)),
                "kind": "indictment", "key": "main", "title": "כתב האישום", "subtitle": None,
                "source_version_ids": [source_version_id],
                "blocks": [{"block": "overview", "items": overview}, {"block": "defendants", "items": defendants}],
                "citations": [], "review": {}}

    return _run_with_framing_retry("indictment_overview", {"counts": parts.count_order, "units": _unit_payload(units, 2500)},
                                   runner=runner, allowed=allowed, corpus_version=corpus_version, assemble=assemble,
                                   units=units, env=env, allegation=True, citation_base=citation_base)


def build_case_guide(*, case_key: str, parts: IndictmentParts, source_version_id: str, runner: ModelRunner,
                     corpus_version: str, citation_base: str, env: str) -> BuildResult:
    units = _uniq(parts.general + parts.counts.get(case_key, []) + parts.appendices.get(case_key, []))
    allowed = {u.id for u in units}

    def assemble(run: ModelRunRecord) -> dict:
        out = run.output
        one = out["one_line"]
        events = []
        for e in out["events"]:
            nd = _norm_date(e["date"], e["date_precision"])
            c = _keep_ids(e["source_unit_ids"], allowed)
            if nd and c:
                events.append(_item(e["text"], c, label=e["title"], date=nd[0], date_precision=nd[1], case_keys=[case_key]))
        events.sort(key=lambda x: x["date"])
        blocks = [
            {"block": "one_line", "items": [_item(one["text"], c)] if (c := _keep_ids(one["source_unit_ids"], allowed)) else []},
            {"block": "alleged", "items": [_item(s["text"], c) for s in out["alleged"] if (c := _keep_ids(s["source_unit_ids"], allowed))]},
            {"block": "people", "items": [_item(p["text"], c, label=p["name"]) for p in out["people"]
                                          if (c := _keep_ids(p["source_unit_ids"], allowed))]},
            {"block": "charges", "items": [_item(ch["text"], c, label=ch["defendant"]) for ch in out["charges"]
                                           if (c := _keep_ids(ch["source_unit_ids"], allowed))]},
            {"block": "events", "items": events},
        ]
        subtitle = re.sub(r"^\s*פרש(?:ת|ה)\s+", "", out["subtitle"]).strip(" \"'״")
        return {"schema_version": SCHEMA_VERSION, "id": str(ids.derived_uuid("guide", "case", case_key, run.id)),
                "kind": "case", "key": case_key, "title": CASE_TITLES.get(case_key, f"תיק {case_key}"),
                "subtitle": subtitle or None, "source_version_ids": [source_version_id], "blocks": blocks,
                "citations": [], "review": {}}

    return _run_with_framing_retry("case_guide", {"case_key": case_key, "units": _unit_payload(units, 2500)},
                                   runner=runner, allowed=allowed, corpus_version=corpus_version, assemble=assemble,
                                   units=units, env=env, allegation=True, citation_base=citation_base)


@dataclass
class WitnessHearing:
    hearing_id: str
    hearing_date: str
    units: list[UnitView]  # the witness's turns and the questions put to them (a bounded sample), in order


def build_witness_guide(*, name: str, slug: str, hearings: list[WitnessHearing], indictment_units: list[UnitView],
                        runner: ModelRunner, corpus_version: str, citation_base: str, env: str,
                        source_version_ids: list[str]) -> BuildResult:
    mentions = [u for u in indictment_units if name_matches(name, u.text)][:12]
    units = _uniq(mentions + [u for h in hearings for u in h.units])
    allowed = {u.id for u in units}
    payload_in = {
        "witness": name,
        "indictment_mentions": _unit_payload(mentions, 1500),
        "hearings": [{"hearing_id": h.hearing_id, "date": h.hearing_date, "units": _unit_payload(h.units, 900)} for h in hearings],
    }

    def assemble(run: ModelRunRecord) -> dict:
        out = run.output
        return {"schema_version": SCHEMA_VERSION, "id": str(ids.derived_uuid("guide", "witness", slug, run.id)),
                "kind": "witness", "key": slug, "title": name, "subtitle": None, "source_version_ids": source_version_ids,
                "blocks": [
                    {"block": "role", "items": [_item(s["text"], c) for s in out["role"] if (c := _keep_ids(s["source_unit_ids"], allowed))]},
                    {"block": "testimony", "items": [_item(s["text"], c) for s in out["testimony"]
                                                     if (c := _keep_ids(s["source_unit_ids"], allowed))]},
                ], "citations": [], "review": {}}

    return _run_with_framing_retry("witness_guide", payload_in, runner=runner, allowed=allowed,
                                   corpus_version=corpus_version, assemble=assemble, units=units, env=env,
                                   allegation=False, citation_base=citation_base)
