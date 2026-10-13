"""Ask the Trial (layer C) — spec §3.4, §23.11, §33.

Order of work for every question:
  1. input limits and normalisation;
  2. refusal of instruction-injection / "answer from memory" requests
     (deterministic, before any model call);
  3. deterministic false-premise checks: case outcomes (as of the requested
     date), attributions of rulings to the court/judges, and misattributed
     speakers;
  4. retrieval hierarchy over *published* material only: published claim
     cards → published hearing digests → published source units (search);
  5. generation by the writer model from that context only;
  6. gates: citation (published only), support, judicial wording, absolute
     wording, risk flags, counter-evidence completeness;
  7. AnswerEnvelope with a permanent permalink, stored and audited.

Sensitive answers (risk flags) are not generated in free text: the envelope
returns ``requires_human_review`` with the relevant citations only.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import contracts, gates, hebrew, ids
from .layers import UnitView, citation_for
from .llm.prompts import ANSWER
from .llm.runner import ModelRunner, unknown_ids_check
from .search.base import SearchBackend, SearchFilters, SearchRequest, query_terms

ASK_ENGINE_VERSION = "ask-engine-1.4"

# ---------------------------------------------------------------------------
# deterministic detectors
# ---------------------------------------------------------------------------
# Patterns are matched on *folded* text: niqqud removed, final letters mapped
# to regular forms (ם→מ, ן→נ, ך→כ, ף→פ, ץ→צ), geresh/gershayim removed,
# lower-case Latin. Write patterns in that form.
INJECTION_PATTERNS = [
    r"התעלמ\w*\s+(?:מ)?(?:כל\s+)?(?:ה)?(?:מקורות|הוראות|הנחיות|כללימ|ציטוטימ)",
    # an instruction to write a given assertion: "…וכתוב שאליעז הודה ש…" (not "מה כתוב שם")
    r"(?:^|\sו)(?:כתוב|תכתוב|כתבי|נסח|תנסח|נסחי)\s+(?:לי\s+)?ש",
    r"ignore\s+(?:all\s+|the\s+|previous\s+|your\s+|prior\s+)*(?:instructions|sources|rules)",
    r"system\s*prompt", r"הנחיות\s*(?:ה)?מערכת", r"מהזיכרונ", r"(?:לפי|ממה)\s*(?:מה\s*)?ש?אתה\s*יודע",
    r"(?:בלי|ללא)\s*(?:מקורות|מקור|ציטוטימ|ציטוט)", r"(?:בלי|ללא)\s+ל?(?:צטט|ציט|הסתמכ|הביא\s+מקור)",
    r"אל\s+ת(?:צטט|ביא\s+מקור|סתמכ)", r"(?:גמ|אפילו)\s*אמ\s*אינ\s*(?:לה|לזה|לו)?\s*מקור",
    r"תמציא", r"(?:^|\s)המצא", r"השלמ\s*את\s*(?:ה)?(?:פרט|חסר)", r"(?:כתוב|תכתוב|נסח|תנסח)\s*(?:לי\s*)?(?:הודאה|וידוי)",
    r"act\s+as", r"pretend", r"jailbreak", r"developer\s*mode", r"you\s+are\s+now", r"אתה\s*עכשיו",
    r"שחק\s*את\s*(?:ה)?תפקיד", r"דעתכ\s*(?:ה)?אישית", r"(?:תגיד|תגידי)\s*(?:לי\s*)?(?:מה\s*)?דעתכ",
]
OUTCOME_PATTERNS = {
    "acquittal": [r"(?:^|\s)(?:ו|ש|כש)?זוכה(?:\s|$|\?)", r"זיכוי", r"זיכו\s*את", r"(?:יצא|נמצא|נמצאה)\s*(?:\S+\s*)?זכאי",
                  r"חפ\s*מפשע\s*(?:נקבע|נמצא|הוכרז)"],
    "conviction": [r"הורשע", r"הרשעה", r"הרשיעו", r"(?:^|\s)(?:ה)?אשמ(?:\s|$|\?|,|\.)", r"נמצא\s*(?:\S+\s*)?אשמ", r"נגזר",
                   r"גזר\s*(?:ה)?דינ", r"(?:נגזר|קיבל|שקיבל|יקבל|הוטל)\w*\s*(?:\S+\s*){0,3}עונש", r"עונשו",
                   r"(?:נשלח|נידונ|שנות|לריצוי)\s*(?:\S+\s*){0,2}מאסר", r"נשלח\s*(?:ל)?(?:ה)?כלא", r"ישב\s*(?:ב)?(?:ה)?כלא"],
    "plea_deal": [r"הסדר\s*(?:ה)?טיעונ\s*(?:ש)?(?:נחתמ|אושר)", r"(?:נחתמ|אושר|חתמ\s*על)\s*(?:ה)?הסדר", r"תנאי\s*(?:ה)?הסדר"],
    "pardon_granted": [r"(?:קיבל|הוענקה|העניק\w*|ניתנה|אושרה|אישר)\b[^?.]{0,30}חנינה", r"חנינה\s*(?:ש)?(?:ניתנה|אושרה|הוענקה)",
                       r"(?:^|\s)חוננ"],
    "withdrawal": [r"(?:בוטל|בוטלו|נמחק|נמחקו)\s*(?:ה)?(?:אישומ|אישומימ|כתב\s*(?:ה)?אישומ)", r"חזרה\s*מ(?:ה)?אישומ",
                   r"(?:ה)?תיק\s*נסגר", r"נסגר\s*(?:ה)?תיק"],
    "verdict": [],  # definite references are handled by _definite_verdict_reference
}
_VERDICT_TERMS = re.compile(r"(?:פסק\s*הדינ|הכרעת\s*הדינ|גזר\s*הדינ)")
_VERDICT_NEGATORS = re.compile(r"(?:לפני|עד|טרמ|לקראת|האמ|יינתנ|צפוי)\s*(?:\S+\s*){0,2}$")


def _fold_q(text: str) -> str:
    return hebrew.fold(text).replace('"', "").replace("'", "")


def _definite_verdict_reference(q: str) -> bool:
    for m in _VERDICT_TERMS.finditer(q):
        if not _VERDICT_NEGATORS.search(q[max(0, m.start() - 25):m.start()]):
            return True
    return False


OUTCOME_OF_EVENT = {"acquittal": {"verdict"}, "conviction": {"verdict"}, "plea_deal": {"plea_deal"},
                    "pardon_granted": {"pardon_granted"}, "withdrawal": {"withdrawal", "dismissal"},
                    "verdict": {"verdict"}}
RULING_ATTRIBUTION_RE = re.compile(
    r"(?:איזה|איזו|אילו|מי\s*מה)?\s*(?:שופט|שופטת|שופטים|השופט|השופטת|השופטים|בית\s*(?:ה)?משפט|ההרכב)\s*"
    r"(?:\S+\s+){0,3}?(?:קבע|קבעה|קבעו|פסק|פסקה|פסקו|הכריע|הכריעה|הכריעו|החליט|החליטה|החליטו)\s*(?:כי|ש)\s*(?P<prop>.+)"
)
_SPEECH_VERBS = r"(?:אמר|אמרה|אמרו|העיד|העידה|טען|טענה|הודה|הודתה|סיפר|סיפרה|הצהיר|הצהירה)"
SPEAKER_CLAIM_RE = re.compile(
    r"(?P<who>(?:העד|העדה|השופט|השופטת|התובע|התובעת|הסנגור|הסניגור|עו\"ד|הנאשמ|הנאשמת)"
    r"(?:\s+(?!" + _SPEECH_VERBS + r"(?:\s|$))[^\s,?]+){0,3})\s+" + _SPEECH_VERBS + r"\s*(?:על\s*כך\s*)?(?:כי|ש)\s*(?P<prop>.+)"
)


def detect_injection(question: str) -> list[str]:
    q = _fold_q(question)
    return [p for p in INJECTION_PATTERNS if re.search(p, q)]


def detect_outcome_premises(question: str) -> list[str]:
    q = _fold_q(question)
    out = [name for name, pats in OUTCOME_PATTERNS.items() if any(re.search(p, q) for p in pats)]
    if _definite_verdict_reference(q) and "verdict" not in out:
        out.append("verdict")
    return out


RULING_ATTRIBUTION_VS_RE = re.compile(
    r"(?:קבע|קבעה|קבעו|פסק|פסקה|פסקו|הכריע|הכריעה|הכריעו)\s+(?:כב'\s*)?(?:השופט|השופטת|השופטים|בית\s*(?:ה)?משפט|ההרכב)"
    r"(?:\s+\S+){0,3}?\s*(?:כי|ש)\s*(?P<prop>.+)"
)
RULING_ATTRIBUTION_DASH_RE = re.compile(
    r"(?:השופט|השופטת|השופטים|בית\s*(?:ה)?משפט|ההרכב)\s+(?:קבע|קבעה|קבעו|פסק|פסקה|פסקו|הכריע|הכריעה|הכריעו)\s+(?:כי|ש)?\s*(?P<prop>[^—\-?]+)"
)


RULING_TOPIC_RE = re.compile(
    r"(?:מה|האם|אילו\s+\S+)\s+(?:קבע|קבעה|קבעו|פסק|פסקה|פסקו|הכריע|הכריעה|הכריעו)\s+(?:כב'\s*)?"
    r"(?:בית\s*(?:ה)?משפט|השופט|השופטת|השופטים|ההרכב)(?:\s+\S+){0,5}?\s+"
    r"(?:לגבי|בעניין|בעניינו\s+של|ביחס\s+ל|בנוגע\s+ל|בשאלת|בשאלה|על)\s*(?P<topic>.+)"
)
RULING_TOPIC_NOUN_RE = re.compile(  # "מה הייתה ההכרעה של ההרכב בנוגע ל…"
    r"(?:ה)?(?:הכרעה|הכרעת|קביעה|קביעת|פסיקה|פסיקת)\s+(?:של\s+)?(?:כב'\s*)?(?:בית\s*(?:ה)?משפט|השופט|השופטת|השופטים|ההרכב)"
    r"(?:\s+\S+){0,3}?\s+(?:לגבי|בעניין|בנוגע\s+ל|ביחס\s+ל|על|בשאלת)\s*(?P<topic>.+)"
)


def detect_ruling_topic(question: str) -> str | None:
    """"מה קבע בית המשפט … לגבי X?" presupposes a determination about X."""
    q = hebrew.normalize(question).replace("״", '"').replace("׳", "'")
    m = RULING_TOPIC_RE.search(q) or RULING_TOPIC_NOUN_RE.search(q)
    return m.group("topic").strip(" ?.!") if m else None


_TESTIFY_VERBS = r"(?:אמר|אמרה|העיד|העידה|השיב|השיבה|ענה|ענתה|סיפר|סיפרה|טען|טענה)"


def detect_witness_date(question: str, hearings: list[dict]) -> tuple[str, str] | None:
    """A question that has a named witness testify on a given date: (surname, ISO date)."""
    from .pipeline.protocol import parse_date

    q = hebrew.normalize(question).replace("״", '"').replace("׳", "'")
    date = parse_date(q.replace("ב-", "").replace("ב־", ""))
    if not date:
        m = re.search(r"(\d{1,2})\s+ב(" + "|".join(_HEB_MONTHS) + r")\s+(\d{4})", q)
        date = f"{m.group(3)}-{_HEB_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}" if m else None
    if not date:
        return None
    surnames = {w.split()[-1] for h in hearings for w in (h.get("witnesses") or []) if w and len(w.split()[-1]) > 2}
    for sn in surnames:
        if re.search(rf"{_TESTIFY_VERBS}\s+(?:\S+\s+){{0,2}}?{re.escape(sn)}\b|\b{re.escape(sn)}\s+(?:\S+\s+){{0,1}}?{_TESTIFY_VERBS}\b"
                     rf"|(?:חקירה|חקירת|עדות|עדותו\s+של)\s+(?:\S+\s+){{0,2}}?{re.escape(sn)}\b"
                     rf"|\b{re.escape(sn)}\s+(?:\S+\s+){{0,3}}?(?:בחקירה|בעדות)", q):
            return sn, date
    return None


_HEB_MONTHS = {"ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6, "יולי": 7,
               "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12}


def detect_ruling_attribution(question: str) -> str | None:
    q = hebrew.normalize(question).replace("״", '"').replace("׳", "'")
    for rx in (RULING_ATTRIBUTION_RE, RULING_ATTRIBUTION_VS_RE, RULING_ATTRIBUTION_DASH_RE):
        m = rx.search(q)
        if m and m.group("prop").strip(" ?.!—-"):
            return m.group("prop").strip(" ?.!—-")
    return None


SPEAKER_CLAIM_VS_RE = re.compile(  # "מה אמר השופט בר-עם על כך שנתניהו צודק?"
    _SPEECH_VERBS + r"\s+(?P<who>(?:העד|העדה|השופט|השופטת|התובע|התובעת|הסנגור|הסניגור|עו\"ד|הנאשמ|הנאשמת)"
    r"(?:\s+(?!על\s|כי\s)[^\s,?]+){0,3}?)\s+(?:על\s*כך\s*)?(?:כי|ש)\s*(?P<prop>.+)"
)


def detect_speaker_claim(question: str) -> tuple[str, str] | None:
    shown = hebrew.normalize(question).replace("\u05f4", '"').replace("\u05f3", "'")
    q = shown.replace("ם", "מ")  # 1:1 replacement, so spans index both strings
    m = SPEAKER_CLAIM_RE.search(q) or SPEAKER_CLAIM_VS_RE.search(q)
    if not m:
        return None
    return shown[m.start("who"):m.end("who")].strip(), shown[m.start("prop"):m.end("prop")].strip(" ?.!")


def normalize_question(question: str) -> str:
    return " ".join(hebrew.fold(question).split())


# ---------------------------------------------------------------------------
# store protocol
# ---------------------------------------------------------------------------
@dataclass
class ContextItem:
    unit: UnitView
    bucket: str  # supports | weakens | court | context
    attribution: str | None = None
    origin: str = "search"  # claim_card | digest | search


class AskStore(Protocol):
    def corpus_version(self) -> str: ...
    def outcome_events(self, as_of: dt.datetime) -> list[dict]: ...
    def process_events(self, as_of: dt.datetime) -> list[dict]: ...
    def published_claim_cards(self) -> list[dict]: ...
    def published_digests(self) -> list[dict]: ...
    def public_units(self, unit_ids: list[str]) -> dict[str, UnitView]: ...
    def approved_rulings(self) -> list[dict]: ...
    def judicial_statements_for_terms(self, terms: list[str]) -> list[dict]: ...
    def find_answer(self, key: dict) -> dict | None: ...
    def save_answer(self, record: dict) -> None: ...


@dataclass
class AskConfig:
    answer_base: str
    citation_base: str
    max_question_chars: int = 500
    env: str = "development"
    verify_answers: bool = True
    independent_verifier: bool = False
    max_context: int = 12
    # cost control (13.10.2026): how much the writer / verifier may think (a level or a token budget; "" = model default)
    thinking: str = "low"
    verify_thinking: str = ""


class AskLimited(Exception):
    """A new answer would need the model, and today's budget (site-wide or this visitor's) is spent."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class AskResult:
    envelope: dict
    cached: bool
    gate_report: dict = field(default_factory=dict)
    retrieval_ids: list[str] = field(default_factory=list)
    model_run_id: str | None = None


class AskEngine:
    def __init__(self, store: AskStore, search: SearchBackend, runner: ModelRunner | None, config: AskConfig):
        self.store = store
        self.search = search
        self.runner = runner
        self.cfg = config

    # -- helpers ---------------------------------------------------------------
    def _model_version(self) -> str:
        if self.runner is None:
            return "none"
        sp = self.runner.registry.get("writer")
        return f"{sp.provider}:{sp.model_id}"

    def _envelope(self, *, question: str, normalized: str, as_of: dt.datetime, cv: str, status: str, short: str,
                  sections: list[dict], cited: list[UnitView], warnings: list[str], locale: str,
                  review_state: str = "machine_verified", flags: list[str] | None = None) -> dict:
        aid = str(ids.derived_uuid("answer", normalized, as_of.date().isoformat(), cv, ANSWER.version, ASK_ENGINE_VERSION,
                                   self._model_version(), locale))
        env = {
            "schema_version": "2.0",
            "answer_id": aid,
            "permalink": f"{self.cfg.answer_base}{aid}",
            "question": question,
            "normalized_question": normalized,
            "answer_status": status,
            "as_of": as_of.replace(microsecond=0).isoformat(),
            "answer_short": short,
            "sections": sections,
            "citations": [citation_for(u, self.cfg.citation_base) for u in _dedupe_units(cited)],
            "corpus_version": cv,
            "warnings": warnings,
            "review": {"state": review_state, "risk_flags": sorted(set(flags or [])), "reviewer": None, "reviewed_at": None},
            "locale": locale,
            "latest_permalink": None,
        }
        contracts.validate("AnswerEnvelope", env)
        return env

    # -- main --------------------------------------------------------------------
    def answer(self, question: str, *, as_of: dt.datetime | None = None, locale: str = "he",
               client_request_id: str | None = None, before_model=None) -> AskResult:
        """``before_model`` is called right before the first model call of a new answer (never for a stored answer or
        a deterministic one); it raises ``AskLimited`` when the day's budget is spent."""
        q = (question or "").strip()
        q = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", q)
        if not q or len(q) > self.cfg.max_question_chars:
            raise ValueError(f"question must be 1..{self.cfg.max_question_chars} characters")
        as_of = (as_of or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
        normalized = normalize_question(q)
        cv = self.store.corpus_version()
        # the engine version is part of the key: a changed detector must not serve answers cached under the old logic
        key = {"normalized_question": normalized, "as_of_date": as_of.date().isoformat(), "corpus_version": cv,
               "prompt_version": f"{ANSWER.version}+{ASK_ENGINE_VERSION}", "model_version": self._model_version(), "locale": locale}
        cached = self.store.find_answer(key)
        if cached:
            return AskResult(cached["envelope"], True, cached.get("gate_report", {}), cached.get("retrieval_ids", []))
        result = self._answer_uncached(q, normalized, as_of, cv, locale, key=key, before_model=before_model)
        if result.cached:  # the same question over the same evidence was answered before: nothing new to store
            return result
        self.store.save_answer({**key, "answer_id": result.envelope["answer_id"], "question": q,
                                "envelope": result.envelope, "answer_status": result.envelope["answer_status"],
                                "gate_report": result.gate_report, "retrieval_ids": result.retrieval_ids,
                                "model_run_id": result.model_run_id, "client_request_id": client_request_id,
                                "as_of": as_of})
        return result

    def _answer_uncached(self, q: str, normalized: str, as_of: dt.datetime, cv: str, locale: str, *, key: dict | None = None,
                         before_model=None) -> AskResult:
        base = dict(question=q, normalized=normalized, as_of=as_of, cv=cv, locale=locale)

        # 2. refusal
        inj = detect_injection(q)
        if inj:
            env = self._envelope(**base, status="refused",
                                 short="אני עונה רק על סמך החומר שפורסם במאגר, עם ציטוט לכל קביעה. איני יכול להתעלם מהמקורות, להשלים פרטים מהזיכרון או לנסח טקסט שאינו נשען על המקור.",
                                 sections=[{"kind": "limitation", "text": "הבקשה כוללת הוראה לחרוג ממדיניות המקורות של המאגר.", "citation_ids": []}],
                                 cited=[], warnings=["refused_instruction"], review_state="machine_verified")
            return AskResult(env, False, {"refusal": inj})

        # 3a. outcome premises
        premises = detect_outcome_premises(q)
        if premises:
            outcome_events = self.store.outcome_events(as_of)
            happened = {e["outcome"] for e in outcome_events if e.get("outcome")}
            false = [p for p in premises if not (OUTCOME_OF_EVENT[p] & happened)]
            if false:
                return self._outcome_correction(base, false, as_of)

        # 3b. ruling attribution
        prop = detect_ruling_attribution(q)
        if prop:
            corr = self._ruling_check(base, prop)
            if corr is not None:
                return corr

        topic = detect_ruling_topic(q)
        if topic and not prop:
            corr = self._ruling_check(base, topic, topic_mode=True)
            if corr is not None:
                return corr

        # 3c. witness on a date when they did not testify
        hearings_fn = getattr(self.store, "published_hearings", None)
        if hearings_fn is not None:
            hearings = hearings_fn()
            wd = detect_witness_date(q, hearings)
            if wd:
                corr = self._witness_date_check(base, wd[0], wd[1], hearings)
                if corr is not None:
                    return corr

        # 3d. speaker attribution
        sc = detect_speaker_claim(q)
        if sc:
            corr = self._speaker_check(base, *sc)
            if corr is not None:
                return corr

        # 4. retrieval hierarchy
        context, origins = self._retrieve(q)
        retrieval_ids = [c.unit.id for c in context]
        if not context:
            env = self._envelope(**base, status="insufficient_published_evidence",
                                 short="לא נמצא בחומר שפורסם במאגר מידע שמאפשר לענות על השאלה. ייתכן שהנושא טרם נקלט או טרם עבר בדיקה ופרסום.",
                                 sections=[{"kind": "limitation", "text": "המאגר עונה רק מחומר שפורסם ועבר בדיקה.", "citation_ids": []}],
                                 cited=[], warnings=[])
            return AskResult(env, False, {"retrieval": origins}, [])

        flags_q = gates.risk_flags(q)
        if self.runner is None:
            return self._citations_only(base, context, ["no_writer_model"], flags_q, origins)

        # 4b. the same question over the same published evidence was answered before (another day, or before an
        # unrelated publication changed the corpus version): reuse it — the answer could only change with the evidence
        by_evidence = getattr(self.store, "find_answer_by_evidence", None)
        if key is not None and by_evidence is not None:
            prev = by_evidence(key, retrieval_ids)
            if prev:
                return AskResult(prev["envelope"], True, prev.get("gate_report", {}), prev.get("retrieval_ids", []))
        if before_model is not None:
            before_model()

        # 5. generation
        payload = {"question": q, "as_of": as_of.date().isoformat(), "context": [
            {"id": c.unit.id, "bucket": c.bucket, "attribution": c.attribution, "speaker": c.unit.speaker_label,
             "speaker_role": c.unit.speaker_role, "unit_type": c.unit.unit_type, "text": c.unit.text[:1500],
             "judicial_level": c.unit.judicial_level} for c in context]}
        allowed = {c.unit.id for c in context}
        run = self.runner.run("answer", payload, input_source_ids=sorted(allowed), corpus_version=cv,
                              semantic_check=unknown_ids_check(allowed, "sections[].citation_ids[]", "answer_short_citation_ids[]"),
                              thinking=self.cfg.thinking or None)
        if not run.ok:
            return self._citations_only(base, context, ["generation_failed"], flags_q, origins, run.id)
        draft = run.output
        if draft["answer_status"] == "refused":
            env = self._envelope(**base, status="refused", short=draft["answer_short"] or "הבקשה נדחתה.",
                                 sections=[], cited=[], warnings=["model_refused"])
            return AskResult(env, False, {"retrieval": origins}, retrieval_ids, run.id)
        if draft["answer_status"] == "insufficient_published_evidence":
            env = self._envelope(**base, status="insufficient_published_evidence", short=draft["answer_short"],
                                 sections=[s for s in draft["sections"] if s["kind"] == "limitation"], cited=[], warnings=[])
            return AskResult(env, False, {"retrieval": origins}, retrieval_ids, run.id)

        units = {c.unit.id: c.unit for c in context}
        sections = [dict(s) for s in draft["sections"]]
        # contradiction completeness: weakening context must be represented
        weak_ctx = [c for c in context if c.bucket == "weakens"]
        if weak_ctx and not any(s["kind"] == "weakens" for s in sections):
            sections.append({"kind": "weakens", "text": "חומר שמחליש או מסייג: " + " | ".join(
                f"{c.unit.speaker_label or 'מקור'}: \"{_clip(c.unit.text, 25)}\"" for c in weak_ctx[:3]),
                "citation_ids": [c.unit.id for c in weak_ctx[:3]]})
        assertions = [gates.Assertion("answer_short", draft["answer_short"], draft.get("answer_short_citation_ids", []),
                                      kind="fact" if draft.get("answer_short_citation_ids") else "limitation")]
        assertions += [gates.Assertion(f"sections/{i}", s["text"], s["citation_ids"], kind=s["kind"])
                       for i, s in enumerate(sections)]
        facts = {u.id: u.facts() for u in units.values()}
        flags = set(flags_q)
        for a in assertions:
            flags.update(gates.risk_flags(a.text))
        verdict = None
        vrun_id = None
        if self.cfg.verify_answers:
            vrun = self.runner.run("verify", {
                "assertions": [{"path": a.path, "text": a.text, "citation_ids": a.citation_ids} for a in assertions
                               if a.kind not in gates.NON_FACTUAL_SECTION_KINDS],
                "sources": [{"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role, "text": u.text[:1500],
                             "judicial_level": u.judicial_level} for u in units.values()]},
                input_source_ids=sorted(allowed), corpus_version=cv, thinking=self.cfg.verify_thinking or None)
            verdict = vrun.output.get("verdict") if vrun.ok else None
            vrun_id = vrun.id
        results = [
            gates.citation_gate(assertions, facts, require_published=True),
            gates.support_gate(assertions, facts),
            gates.judicial_wording_gate(assertions, facts),
            gates.absolute_wording_gate(assertions, status=None),
            gates.provenance_gate([run.model_family], env=self.cfg.env),
        ]
        if self.cfg.verify_answers:
            results.append(gates.verifier_gate(verdict, independent_family=self.cfg.independent_verifier, sensitive=bool(flags)))
        decision = gates.decide(results, flags=flags)
        report = {**decision.report(), "retrieval": origins, "verifier_run_id": vrun_id}
        if decision.state != "machine_verified":
            return self._citations_only(base, context, ["requires_human_review"], sorted(flags), origins, run.id, report)
        cited = [units[c] for s in sections for c in s["citation_ids"] if c in units]
        cited += [units[c] for c in draft.get("answer_short_citation_ids", []) if c in units]
        status = "false_premise_corrected" if draft["answer_status"] == "false_premise_corrected" else "answered"
        warnings = ["automatic_answer"] + (["premise:" + p for p in draft.get("premise_issues", [])])
        env = self._envelope(**base, status=status, short=draft["answer_short"], sections=sections, cited=cited,
                             warnings=warnings, flags=sorted(flags))
        return AskResult(env, False, report, retrieval_ids, run.id)

    # -- branches ----------------------------------------------------------------
    def _citations_only(self, base: dict, context: list[ContextItem], warnings: list[str], flags: list[str],
                        origins: dict, run_id: str | None = None, report: dict | None = None) -> AskResult:
        units = [c.unit for c in context[:6]]
        env = self._envelope(**base, status="requires_human_review",
                             short="לשאלה זו אין עדיין תשובה כתובה שעברה בדיקה. אלה הקטעים הרלוונטיים במקור, בלי פרשנות:",
                             sections=[{"kind": "limitation", "text": "תשובה מנוסחת לנושא זה מחייבת בדיקה אנושית לפני פרסום.", "citation_ids": []}],
                             cited=units, warnings=warnings, review_state="human_review_required", flags=flags)
        return AskResult(env, False, {**(report or {}), "retrieval": origins}, [u.id for u in units], run_id)

    def _outcome_correction(self, base: dict, false: list[str], as_of: dt.datetime) -> AskResult:
        process = self.store.process_events(as_of)
        lines = [f"נכון ל־{as_of.date().isoformat()} לא נרשמה במאגר הכרעה או תוצאה סופית של ההליך (ת״פ 67104-01-20), ולכן ההנחה בשאלה אינה נכונה. ההליך מתנהל וכל הנאשמים נהנים מחזקת החפות."]
        cited: list[UnitView] = []
        for e in process:
            if e["event_type"] == "pardon_requested":
                lines.append(f"{e['title']} ({e['occurred_at'][:10]}). זהו אירוע תהליכי ואינו תוצאת ההליך.")
            if e.get("source_unit_ids"):
                cited += list(self.store.public_units(e["source_unit_ids"]).values())
        sections = [{"kind": "status", "text": " ".join(lines[1:]) or "אין אירועי תוצאה רשומים.", "citation_ids": [u.id for u in cited]}] if len(lines) > 1 else []
        sections.append({"kind": "limitation", "text": "הסטטוס מבוסס על אירועי ההליך שפורסמו במאגר עד המועד שצוין.", "citation_ids": []})
        env = self._envelope(**base, status="false_premise_corrected", short=lines[0], sections=sections, cited=cited,
                             warnings=[f"false_premise:{p}" for p in false])
        return AskResult(env, False, {"false_premise": false})

    def _witness_date_check(self, base: dict, surname: str, date: str, hearings: list[dict]) -> AskResult | None:
        on_date = [h for h in hearings if h["hearing_date"] == date]
        testified = [h["hearing_date"] for h in hearings if any(w.split()[-1] == surname for w in (h.get("witnesses") or []))]
        if on_date and any(any(w.split()[-1] == surname for w in (h.get("witnesses") or [])) for h in on_date):
            return None  # premise holds → normal path
        when = ", ".join(testified) if testified else "—"
        if on_date:
            short = (f"לפי החומר שפורסם, {surname} לא העיד בדיון מיום {date}. "
                     f"דיונים שפורסמו שבהם העיד: {when}.")
        else:
            short = f"לא פורסם במאגר פרוטוקול של דיון מיום {date}. דיונים שפורסמו שבהם העיד {surname}: {when}."
        env = self._envelope(**base, status="false_premise_corrected", short=short,
                             sections=[{"kind": "limitation", "text": "התשובה מבוססת על רשימת העדים בכל דיון שפורסם במאגר.",
                                        "citation_ids": []}],
                             cited=[], warnings=["false_premise:witness_date"])
        return AskResult(env, False, {"false_premise": ["witness_date"]})

    def _ruling_check(self, base: dict, prop: str, topic_mode: bool = False) -> AskResult | None:
        terms = [t for t in query_terms(prop) if len(t) > 2]
        if not terms:
            return None
        rulings = self.store.approved_rulings()
        best = None
        for r in rulings:
            r_terms = set(hebrew.search_terms(r["text"] + " " + (r.get("summary") or "")))
            ratio = len(set(terms) & r_terms) / len(set(terms))
            if ratio >= 0.6 and (best is None or ratio > best[0]):
                best = (ratio, r)
        if best is not None:
            return None  # supported by an approved ruling → normal answering path
        related = self.store.judicial_statements_for_terms(terms)[:3]
        units = self.store.public_units([r["source_unit_id"] for r in related])
        sections = []
        if units:
            level_he = {"question_or_comment": "שאלה או הערה", "interim_observation": "הערת ביניים",
                        "procedural_decision": "החלטה דיונית", "substantive_ruling": "הכרעה"}
            for r in related:
                if r["source_unit_id"] in units:
                    sections.append({"kind": "court_position",
                                     "text": f"בחומר שפורסם יש {level_he.get(r['level'], 'אמירה')} של בית המשפט בנושא קרוב; זו אינה קביעה כי {_clip(prop, 20)}.",
                                     "citation_ids": [r["source_unit_id"]]})
        sections.append({"kind": "limitation", "text": "המאגר מבחין בין שאלה או הערה של שופט לבין החלטה או הכרעה.", "citation_ids": []})
        short = (f"לא נמצאה בחומר שפורסם הכרעה של בית המשפט בעניין {_clip(prop, 25)}. שאלה או הערה של שופט במהלך הדיון אינה הכרעה."
                 if topic_mode else
                 f"לא נמצאה בחומר שפורסם קביעה של בית המשפט כי {_clip(prop, 25)}. ההנחה שבשאלה אינה נתמכת במקורות.")
        env = self._envelope(**base, status="false_premise_corrected", short=short,
                             sections=sections, cited=list(units.values()), warnings=["false_premise:ruling_attribution"])
        return AskResult(env, False, {"false_premise": ["ruling_attribution"]})

    def _speaker_check(self, base: dict, who: str, prop: str) -> AskResult | None:
        resp = self.search.search(SearchRequest(prop, SearchFilters(published_only=True), limit=8))
        who_key = hebrew.fold(who.split()[-1])
        terms = set(t for t in query_terms(prop) if len(t) > 2)
        if not terms:
            return None

        def overlap(text: str) -> float:
            return len(terms & set(hebrew.search_terms(text))) / len(terms)

        # short propositions ("נתניהו צודק") need every content word: "אדוני כמובן צודק" said to counsel is not it
        need = 0.75 if len(terms) <= 3 else 0.5
        by_named = [h for h in resp.hits if h.speaker_label and who_key in hebrew.fold(h.speaker_label) and overlap(h.text) >= need]
        if by_named:
            return None  # the named speaker did say something close → normal answering path
        others = [h for h in resp.hits if overlap(h.text) >= 0.6 and h.speaker_label]
        units = self.store.public_units([others[0].source_unit_id]) if others else {}
        if others and units:
            top = others[0]
            short = f"בחומר שפורסם הדברים אינם מופיעים בדברי {who}; קטע דומה מופיע בדברי {top.speaker_label}."
            sections = [{"kind": "why", "text": f"{top.speaker_label}: \"{_clip(top.text, 30)}\"", "citation_ids": [top.source_unit_id]}]
        else:
            short = f"בחומר שפורסם לא נמצא ש{who} אמר את הדברים המיוחסים בשאלה."
            sections = [{"kind": "limitation", "text": "המאגר מייחס דברים רק לדובר שאמר אותם לפי הפרוטוקול.", "citation_ids": []}]
        env = self._envelope(**base, status="false_premise_corrected", short=short, sections=sections,
                             cited=list(units.values()), warnings=["false_premise:speaker_attribution"])
        return AskResult(env, False, {"false_premise": ["speaker_attribution"]})

    def _retrieve(self, q: str) -> tuple[list[ContextItem], dict]:
        terms = set(query_terms(q))
        items: list[ContextItem] = []
        seen: set[str] = set()
        origins: dict[str, Any] = {"claim_cards": [], "digests": [], "search": 0}

        def add(uid_list: list[str], bucket: str, origin: str, attribution: str | None = None) -> None:
            units = self.store.public_units([u for u in uid_list if u not in seen])
            for uid in uid_list:
                if uid in units and uid not in seen:
                    seen.add(uid)
                    items.append(ContextItem(units[uid], bucket, attribution, origin))

        if terms:
            for card in self.store.published_claim_cards():
                p = card["payload"]
                c_terms = set(hebrew.search_terms(p["question"] + " " + p["claim_text"]))
                if len(terms & c_terms) / max(1, len(terms)) >= 0.5:
                    origins["claim_cards"].append(card["object_id"])
                    for ev in p.get("support", []):
                        add(ev["citation_ids"], "supports", "claim_card")
                    for ev in p.get("weakness", []):
                        add(ev["citation_ids"], "weakens", "claim_card")
                    if p.get("court_position"):
                        add(p["court_position"]["citation_ids"], "court", "claim_card")
            for dg in self.store.published_digests():
                p = dg["payload"]
                d_terms = set(hebrew.search_terms(" ".join(p.get("topics", [])) + " " + p.get("summary", "")))
                if len(terms & d_terms) / max(1, len(terms)) >= 0.5:
                    origins["digests"].append(p["hearing_id"])
                    for s in p.get("summary_sentences", []):
                        add(s["citation_ids"], "context", "digest")
        if len(items) < self.cfg.max_context:
            resp = self.search.search(SearchRequest(q, SearchFilters(published_only=True), limit=self.cfg.max_context))
            origins["search"] = len(resp.hits)
            # relevance floor: a hit needs a lexical/identifier/graph signal or agreement of two signals;
            # fuzzy-only matches (one n-gram or vector signal) are not enough to answer from
            relevant = [h for h in resp.hits if {"exact", "terms", "graph"} & set(h.signals) or len(h.signals) >= 2]
            origins["search_relevant"] = len(relevant)
            hit_ids = [h.source_unit_id for h in relevant]
            # a question is phrased like the user's question and ranks high; the witness's answer ("נכון", "לא זוכר")
            # does not. Keep every Q/A exchange whole: question first, then its answer.
            partners_fn = getattr(self.store, "exchange_partners", None)
            partners = partners_fn(hit_ids) if partners_fn else {}
            ordered: list[str] = []
            for uid in hit_ids:
                p = partners.get(uid)
                pair = [uid, p] if p and relevant_type(relevant, uid) == "question" else ([p, uid] if p else [uid])
                ordered.extend(x for x in pair if x not in ordered)
            origins["exchange_partners_added"] = len([x for x in ordered if x not in hit_ids])
            add(ordered, "context", "search")
        return items[: self.cfg.max_context + origins.get("exchange_partners_added", 0)][:MAX_CONTEXT_WITH_PAIRS], origins


MAX_CONTEXT_WITH_PAIRS = 24


def relevant_type(hits: list, uid: str) -> str | None:
    for h in hits:
        if h.source_unit_id == uid:
            return h.unit_type
    return None


def _clip(text: str, words: int) -> str:
    w = text.replace("\n", " ").split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def _dedupe_units(units: list[UnitView]) -> list[UnitView]:
    seen: set[str] = set()
    out = []
    for u in units:
        if u.id not in seen:
            seen.add(u.id)
            out.append(u)
    return out
