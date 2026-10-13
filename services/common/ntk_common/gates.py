"""Publication gates (spec §12.4, §16.5, §23.6, §24, §30.2).

Each gate returns ``GateResult`` objects; ``decide`` folds them into a
review decision:

* ``rejected``               – contract/citation failure; never publishable
* ``human_review_required``  – risk flags, judicial wording, writer/verifier
                               disagreement, single model family on a
                               sensitive item, Q/A "affirmed" wording
* ``machine_verified``       – passed every automatic gate; still needs an
                               explicit publish action

Nothing is ever published by a gate; publication is a separate, audited
admin action.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import hebrew

# --- vocabulary ---------------------------------------------------------------
# Phrases that assert a court *determination*. Matched on folded text.
DETERMINATION_PATTERNS = [
    r"בית\s*המשפט\s*(?:קבע|פסק|הכריע|החליט|דחה|קיבל)",
    r"(?:השופט|השופטת|השופטים|ההרכב|המותב)\s*(?:קבע|קבעה|קבעו|פסק|פסקה|פסקו|הכריע|הכריעה|הכריעו|החליט|החליטה|החליטו)",
    r"(?:^|\s)נקבע\s*(?:כי|ש)",
    # the court as subject earlier in the sentence: "בית המשפט פתח את הדיון, ובהמשך קבע בהחלטה כי…"
    r"(?:^|\s)ו?(?:ב?המשך\s+)?(?:קבע|קבעה|קבעו|פסק|פסקה|הכריע|הכריעה)\s+(?:בהחלט|כי(?:\s|$)|ש)",
    r"(?:^|\s)הוכרע\s*(?:כי|ש)",
    r"(?:^|\s)נפסק\s*(?:כי|ש)",
    r"בפסק\s*הדין",
]
ABSOLUTE_PATTERNS = [r"(?:^|\s)הופרכ", r"(?:^|\s)הוכח(?:ה|ו)?(?:\s|$)", r"הוכח\s*סופית", r"(?:^|\s)מופרכ"]
RISK_PATTERNS: dict[str, list[str]] = {
    "motive_or_conspiracy": [r"מניע\s*פוליטי", r"קנוניה", r"תפירת\s*תיק", r"(?:^|\s)תפור", r"רדיפה\s*פוליטית", r"הפיכה\s*משפטית",
                             r"ציד\s*מכשפות", r"להפיל\s*את"],
    "investigator_offense": [r"(?:החוקרים|המשטרה|הפרקליטות|הפרקליטים|התביעה)\s*(?:עבר|עברו|ביצע|ביצעו)\s*עביר",
                             r"שיבוש\s*הליכי", r"עינוי", r"עינו", r"סחיטה", r"איימו\s*על", r"הדליפו"],
    "witness_lied": [r"(?:^|\s)שיקר", r"(?:^|\s)שקרן", r"עדות\s*שקר", r"(?:^|\s)משקר"],
    "final_legal_conclusion": [r"(?:^|\s)אשם(?:\s|$)", r"(?:^|\s)הורשע", r"(?:^|\s)זוכה(?:\s|$)", r"(?:^|\s)זיכוי", r"הרשעה",
                               r"ביצע\s*(?:את\s*)?(?:ה)?עביר", r"לקח\s*שוחד", r"קיבל\s*שוחד"],
}
NON_FACTUAL_SECTION_KINDS = {"limitation"}


def _fold(text: str) -> str:
    return hebrew.normalize(text).replace("״", '"').replace("׳", "'")


def find_determination_language(text: str) -> list[str]:
    t = _fold(text)
    return [m.group(0) for p in DETERMINATION_PATTERNS for m in re.finditer(p, t)]


def find_absolute_language(text: str) -> list[str]:
    t = _fold(text)
    return [m.group(0).strip() for p in ABSOLUTE_PATTERNS for m in re.finditer(p, t)]


def risk_flags(text: str) -> list[str]:
    t = _fold(text)
    flags = [name for name, pats in RISK_PATTERNS.items() if any(re.search(p, t) for p in pats)]
    if find_determination_language(text):
        flags.append("court_determined_wording")
    return sorted(set(flags))


# --- data passed to gates -------------------------------------------------------
@dataclass
class UnitFacts:
    id: str
    text: str
    speaker_role: str | None
    unit_type: str
    published: bool
    judicial_level: str | None = None  # from an approved judicial statement
    judicial_human_approved: bool = False


@dataclass
class Assertion:
    path: str
    text: str
    citation_ids: list[str]
    kind: str = "fact"  # fact | limitation | status
    attribution: str | None = None
    exchange_id: str | None = None


@dataclass
class GateResult:
    gate: str
    passed: bool
    severity: str = "error"  # error → reject | review → human review | info
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"gate": self.gate, "passed": self.passed, "severity": self.severity, "details": self.details}


@dataclass
class GateDecision:
    state: str  # rejected | human_review_required | machine_verified
    results: list[GateResult]
    risk_flags: list[str]

    def report(self) -> dict:
        return {"state": self.state, "risk_flags": self.risk_flags, "gates": [r.to_dict() for r in self.results]}

    @classmethod
    def from_report(cls, report: dict) -> GateDecision:
        return cls(report["state"], [GateResult(g["gate"], g["passed"], g.get("severity", "error"), g.get("details") or [])
                                     for g in report.get("gates", [])], list(report.get("risk_flags") or []))


# --- gates ----------------------------------------------------------------------
def citation_gate(assertions: Iterable[Assertion], units: dict[str, UnitFacts], *, require_published: bool) -> GateResult:
    details = []
    for a in assertions:
        if a.kind in NON_FACTUAL_SECTION_KINDS:
            continue
        if not a.text.strip():
            continue
        if not a.citation_ids:
            details.append({"path": a.path, "problem": "missing_citation"})
            continue
        for cid in a.citation_ids:
            u = units.get(cid)
            if u is None:
                details.append({"path": a.path, "problem": "unknown_source_unit", "id": cid})
            elif require_published and not u.published:
                details.append({"path": a.path, "problem": "unpublished_source_unit", "id": cid})
    return GateResult("citation", not details, "error", details)


def quote_gate(quotes: Iterable[tuple[str, str, str]], units: dict[str, UnitFacts]) -> GateResult:
    """quotes: (path, source_unit_id, quote). Quoted text must occur in the unit."""
    details = []
    for path, uid, quote in quotes:
        if not quote:
            continue
        u = units.get(uid)
        if u is None or hebrew.fold(quote).strip(' ."') not in hebrew.fold(u.text):
            details.append({"path": path, "problem": "quote_not_in_source", "id": uid})
    return GateResult("quote", not details, "error", details)


def support_gate(assertions: Iterable[Assertion], units: dict[str, UnitFacts], *, min_overlap: float = 0.2) -> GateResult:
    """Deterministic lexical support check: an assertion must share content
    terms with what it cites. It is a floor, not a proof; the verifier and
    humans do the semantic check."""
    details = []
    stop = {"את", "של", "על", "לא", "כי", "גם", "אמר", "השיב", "שאל", "העד", "בית", "המשפט", "עוד", "זה", "הוא", "היא"}
    for a in assertions:
        if a.kind in NON_FACTUAL_SECTION_KINDS or not a.citation_ids:
            continue
        a_terms = {t for t in hebrew.search_terms(a.text) if len(t) > 2 and t not in stop}
        if not a_terms:
            continue
        cited_terms: set[str] = set()
        for cid in a.citation_ids:
            if cid in units:
                cited_terms |= set(hebrew.search_terms(units[cid].text))
        ratio = len(a_terms & cited_terms) / len(a_terms)
        if ratio < min_overlap:
            details.append({"path": a.path, "problem": "low_lexical_support", "overlap": round(ratio, 3)})
    return GateResult("support", not details, "review", details)


def judicial_wording_gate(assertions: Iterable[Assertion], units: dict[str, UnitFacts]) -> GateResult:
    """'The court determined' wording requires a cited, human-approved
    judicial statement at procedural_decision or substantive_ruling level."""
    details = []
    for a in assertions:
        hits = find_determination_language(a.text)
        if not hits:
            continue
        ok = any(
            (u := units.get(c)) is not None and u.judicial_level in {"procedural_decision", "substantive_ruling"}
            and u.judicial_human_approved
            for c in a.citation_ids
        )
        if not ok:
            details.append({"path": a.path, "problem": "determination_wording_without_ruling", "phrases": hits})
    return GateResult("judicial_wording", not details, "error", details)


def absolute_wording_gate(assertions: Iterable[Assertion], *, status: str | None) -> GateResult:
    details = []
    for a in assertions:
        hits = find_absolute_language(a.text)
        if hits and status not in {"court_determined", "rejected"}:
            details.append({"path": a.path, "problem": "absolute_wording_without_status_rule", "phrases": hits})
    return GateResult("absolute_wording", not details, "error", details)


def attribution_gate(assertions: Iterable[Assertion], units: dict[str, UnitFacts],
                     verified_affirmations: set[str] | None = None) -> GateResult:
    verified_affirmations = verified_affirmations or set()
    details = []
    expected_roles = {
        "witness_said": {"witness"},
        "counsel_asked": {"prosecution", "defense", "counsel"},
        "prosecution_argued": {"prosecution"},
        "defense_argued": {"defense", "defendant"},
        "judge_asked": {"judge"},
        "judge_commented": {"judge"},
        "court_decided": {"court", "judge"},
    }
    for a in assertions:
        if not a.attribution:
            continue
        cited = [units[c] for c in a.citation_ids if c in units]
        if a.attribution == "witness_affirmed_question":
            types = {u.unit_type for u in cited}
            if not {"question", "answer"} <= types:
                details.append({"path": a.path, "problem": "affirmation_must_cite_question_and_answer"})
            if not a.exchange_id or a.exchange_id not in verified_affirmations:
                details.append({"path": a.path, "problem": "affirmation_not_verified", "exchange_id": a.exchange_id})
            continue
        roles = expected_roles.get(a.attribution)
        if roles and not any((u.speaker_role or "") in roles for u in cited):
            details.append({"path": a.path, "problem": "attribution_speaker_mismatch", "attribution": a.attribution,
                            "cited_roles": sorted({u.speaker_role or "" for u in cited})})
    return GateResult("attribution", not details, "review", details)


def counterevidence_gate(*, available_weakening: int, included_weakening: int) -> GateResult:
    ok = available_weakening == 0 or included_weakening > 0
    return GateResult("counterevidence", ok, "review",
                      [] if ok else [{"problem": "weakening_material_omitted", "available": available_weakening}])


def verifier_gate(verdict: str | None, *, independent_family: bool, sensitive: bool) -> GateResult:
    if verdict is None:
        return GateResult("verifier", False, "review", [{"problem": "not_verified"}])
    if verdict == "fail":
        return GateResult("verifier", False, "review", [{"problem": "writer_verifier_disagreement"}])
    if verdict == "needs_human":
        return GateResult("verifier", False, "review", [{"problem": "verifier_requested_human"}])
    if sensitive and not independent_family:
        return GateResult("verifier", False, "review", [{"problem": "sensitive_item_single_model_family"}])
    return GateResult("verifier", True, "info")


def provenance_gate(model_families: Iterable[str], *, env: str) -> GateResult:
    fams = set(model_families)
    if "mock" in fams and env not in {"development", "test"}:
        return GateResult("provenance", False, "error", [{"problem": "mock_model_output_outside_dev"}])
    return GateResult("provenance", True, "info")


def decide(results: list[GateResult], *, flags: Iterable[str] = (), force_human: bool = False) -> GateDecision:
    flags = sorted(set(flags))
    if any(not r.passed and r.severity == "error" for r in results):
        state = "rejected"
    elif force_human or flags or any(not r.passed and r.severity == "review" for r in results):
        state = "human_review_required"
    else:
        state = "machine_verified"
    return GateDecision(state, results, flags)
