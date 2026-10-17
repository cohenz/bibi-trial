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
from .llm.prompts import ANSWER, ANSWER_DEFENSE, VERIFY_ANSWER_DEFENSE
from .llm.runner import ModelRunner, unknown_ids_check
from .search.base import SearchBackend, SearchFilters, SearchRequest, query_terms

ASK_ENGINE_VERSION = "ask-engine-1.17"

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
    bucket: str  # supports | weakens | court | context | defense | surrounding | prosecution
    attribution: str | None = None
    origin: str = "search"  # claim_card | witness_guide | digest | defense | search


class AskStore(Protocol):
    def corpus_version(self) -> str: ...
    def outcome_events(self, as_of: dt.datetime) -> list[dict]: ...
    def process_events(self, as_of: dt.datetime) -> list[dict]: ...
    def published_claim_cards(self) -> list[dict]: ...
    def published_digests(self) -> list[dict]: ...
    # optional: def published_witness_guides(self) -> list[dict]
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
    max_context: int = 14  # search hits (each Q/A exchange is kept whole, so up to twice as many units)
    guide_context: int = 6  # passages behind the guides of witnesses the question names
    digest_context: int = 6  # passages behind the best-matching hearing digests
    # cost control (13.10.2026): how much the writer / verifier may think (a level or a token budget; "" = model default)
    thinking: str = "low"
    verify_thinking: str = ""
    # editorial lens (13.10.2026, the site owner's decision): "defense" builds the answer around what came out in
    # court against the prosecution's version, from examinations conducted by defense counsel; "neutral" is the
    # earlier balanced answer
    lens: str = "defense"
    defense_context: int = 16  # passages from examinations by defense counsel (each Q/A exchange kept whole)
    surround_exchanges: int = 10  # of those, how many come with the two passages before and after them
    prosecution_context: int = 4  # indictment passages, and exchanges of the prosecution's direct examination
    documents_context: int = 5  # court decisions on the topic, and as many passages from documents the parties filed


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
    @property
    def _defense(self) -> bool:
        return self.cfg.lens == "defense"

    @property
    def _prompt(self):
        return ANSWER_DEFENSE if self._defense else ANSWER

    def _model_version(self) -> str:
        if self.runner is None:
            return "none"
        sp = self.runner.registry.get("writer")
        return f"{sp.provider}:{sp.model_id}"

    def _envelope(self, *, question: str, normalized: str, as_of: dt.datetime, cv: str, status: str, short: str,
                  sections: list[dict], cited: list[UnitView], warnings: list[str], locale: str,
                  review_state: str = "machine_verified", flags: list[str] | None = None) -> dict:
        aid = str(ids.derived_uuid("answer", normalized, as_of.date().isoformat(), cv, self._prompt.version, ASK_ENGINE_VERSION,
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

    def _key(self, normalized: str, as_of: dt.datetime, cv: str, locale: str) -> dict:
        # the engine version is part of the key: a changed detector must not serve answers cached under the old logic
        return {"normalized_question": normalized, "as_of_date": as_of.date().isoformat(), "corpus_version": cv,
                "prompt_version": f"{self._prompt.version}+{ASK_ENGINE_VERSION}", "model_version": self._model_version(),
                "locale": locale}

    def inflight_key(self, question: str, locale: str = "he") -> str:
        """One key per question being answered right now: a second request for it waits for the first (13.10.2026 —
        a defense-lens answer takes about a minute, and a visitor who asks again must not start a second paid run)."""
        return "ntk:ask:inflight:" + ids.sha256_json([normalize_question((question or "").strip()), locale,
                                                       self._prompt.version, ASK_ENGINE_VERSION])

    def stored(self, question: str, *, as_of: dt.datetime | None = None, locale: str = "he") -> AskResult | None:
        """The stored answer to this question for today and this corpus, without computing anything."""
        as_of = (as_of or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
        cached = self.store.find_answer(self._key(normalize_question((question or "").strip()), as_of,
                                                  self.store.corpus_version(), locale))
        if not cached:
            return None
        return AskResult(cached["envelope"], True, cached.get("gate_report", {}), cached.get("retrieval_ids", []))

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
        key = self._key(normalized, as_of, cv, locale)
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

        payload = {"question": q, "as_of": as_of.date().isoformat(), "context": [
            {"id": c.unit.id, "bucket": c.bucket, "attribution": c.attribution, "speaker": c.unit.speaker_label,
             "speaker_role": c.unit.speaker_role, "unit_type": c.unit.unit_type,
             "hearing_date": c.unit.hearing_date, "examination": c.unit.examination_phase,
             "witness_examined": c.unit.witness_label, "document": c.unit.document_title,
             "text": c.unit.text[:700 if c.bucket == "surrounding" else 1500],
             "judicial_level": c.unit.judicial_level} for c in context]}
        allowed = {c.unit.id for c in context}
        # everything the model would see about the evidence: passages, their roles, speakers, rulings and text
        context_hash = ids.sha256_json(payload["context"])

        # 4b. the same question over exactly the same evidence was answered before (another day, or before an
        # unrelated publication changed the corpus version): reuse it — the answer could only change with the evidence
        by_evidence = getattr(self.store, "find_answer_by_evidence", None)
        if key is not None and by_evidence is not None:
            prev = by_evidence(key, context_hash)
            if prev:
                return AskResult(prev["envelope"], True, prev.get("gate_report", {}), prev.get("retrieval_ids", []))
        # the budget counts only calls that cost: a stored model answer for this exact input is free
        if before_model is not None:
            stored = self.runner.store.get_run(self.runner.request_for(self._prompt.task_type, payload)["run_id"])
            if stored is None or not stored.ok:
                before_model()

        # 5. generation
        run = self.runner.run(self._prompt.task_type, payload, input_source_ids=sorted(allowed), corpus_version=cv,
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
        # ids written into the prose become citations of that sentence, and leave the text (13.10.2026)
        draft = dict(draft)
        draft["answer_short"], draft["answer_short_citation_ids"] = move_inline_ids(
            draft["answer_short"], draft.get("answer_short_citation_ids", []), allowed)
        for i, sec in enumerate(sections):
            sec["text"], sec["citation_ids"] = move_inline_ids(sec["text"], sec["citation_ids"], allowed)
            sec["_vpath"] = f"sections/{i}"  # the verifier's numbering, kept through pruning; removed before publishing
        # contradiction completeness: weakening context must be represented (a claim card's weakness is material
        # against the defense's claim, so under the defense lens it is the prosecution's side)
        weak_kind = "prosecution" if self._defense else "weakens"
        weak_ctx = [c for c in context if c.bucket == "weakens"]
        if weak_ctx and not any(s["kind"] == weak_kind for s in sections):
            sections.append({"kind": weak_kind, "text": "חומר שמחליש או מסייג: " + " | ".join(
                f"{c.unit.speaker_label or 'מקור'}: \"{_clip(c.unit.text, 25)}\"" for c in weak_ctx[:3]),
                "citation_ids": [c.unit.id for c in weak_ctx[:3]]})
        assertions = [gates.Assertion("answer_short", draft["answer_short"], draft.get("answer_short_citation_ids", []),
                                      kind="fact" if draft.get("answer_short_citation_ids") else "limitation")]
        assertions += [gates.Assertion(f"sections/{i}", s["text"], s["citation_ids"], kind=s["kind"])
                       for i, s in enumerate(sections)]
        facts = {u.id: u.facts() for u in units.values()}
        flags = set(flags_q)
        for a in assertions:
            flags.update(answer_flags(a))
        verdict = None
        vrun_id = None
        pruned: list[dict] = []
        short_vpath = "answer_short"  # the verifier's path for the text now in answer_short
        if self.cfg.verify_answers:
            vrun = self.runner.run(VERIFY_ANSWER_DEFENSE.task_type if self._defense else "verify", {
                "assertions": [{"path": a.path, "text": a.text, "citation_ids": a.citation_ids} for a in assertions
                               if a.kind not in gates.NON_FACTUAL_SECTION_KINDS],
                "sources": [{"id": u.id, "speaker": u.speaker_label, "speaker_role": u.speaker_role,
                             "hearing_date": u.hearing_date, "examination": u.examination_phase,
                             "witness_examined": u.witness_label, "document": u.document_title, "text": u.text[:1500],
                             "judicial_level": u.judicial_level} for u in units.values()]},
                input_source_ids=sorted(allowed), corpus_version=cv, thinking=self.cfg.verify_thinking or None)
            verdict = vrun.output.get("verdict") if vrun.ok else None
            vrun_id = vrun.id
            if verdict == "fail" and vrun.ok and self._defense:
                kept = prune_unapproved(sections, vrun.output)
                if kept is not None:
                    sections, pruned, short = kept
                    if short is not None:
                        draft["answer_short"], draft["answer_short_citation_ids"] = short["text"], short["citation_ids"]
                        short_vpath = short.get("_vpath") or "answer_short"
                        assertions = [gates.Assertion("answer_short", short["text"], short["citation_ids"], kind="fact")] + [
                            a for a in assertions if a.path != "answer_short"]
                    assertions = [a for a in assertions if not a.path.startswith("sections/")]
                    assertions += [gates.Assertion(f"sections/{i}", s["text"], s["citation_ids"], kind=s["kind"])
                                   for i, s in enumerate(sections)]
                    flags = set(flags_q)
                    for a in assertions:
                        flags.update(answer_flags(a))
                    verdict = "pass"
        support_waived: list[str] = []
        if self._defense and self.cfg.verify_answers and verdict == "pass" and vrun_id:
            approved = verifier_approved(vrun.output if vrun.ok else {})
            weak = {d["path"] for d in gates.support_gate(assertions, facts).details}
            by_path = {f"sections/{i}": sec for i, sec in enumerate(sections)}
            drop = []
            for path in sorted(weak):
                vpath = short_vpath if path == "answer_short" else (by_path.get(path) or {}).get("_vpath")
                if vpath in approved:
                    support_waived.append(path)  # the independent verifier read the passages and approved it
                elif path != "answer_short":
                    drop.append(path)
            if drop:
                kept = [sec for i, sec in enumerate(sections) if f"sections/{i}" not in drop or sec["kind"] == "limitation"]
                if sum(1 for sec in kept if sec["kind"] == "defense") >= MIN_DEFENSE_POINTS_AFTER_PRUNING:
                    pruned += [{"path": by_path[pth]["_vpath"], "kind": by_path[pth]["kind"], "text": by_path[pth]["text"],
                                "note": "low lexical support, not approved by the verifier"} for pth in drop]
                    sections = kept
                    assertions = [a for a in assertions if not a.path.startswith("sections/")]
                    assertions += [gates.Assertion(f"sections/{i}", sec["text"], sec["citation_ids"], kind=sec["kind"])
                                   for i, sec in enumerate(sections)]
                    support_waived = [p for p in support_waived if p == "answer_short"] + [
                        f"sections/{i}" for i, sec in enumerate(sections) if sec["_vpath"] in approved
                        and f"sections/{i}" in {d["path"] for d in gates.support_gate(assertions, facts).details}]
        results = [
            gates.citation_gate(assertions, facts, require_published=True),
            gates.support_gate([a for a in assertions if a.path not in support_waived], facts),
            gates.judicial_wording_gate(assertions, facts),
            gates.absolute_wording_gate([a for a in assertions if not attributed_argument(a)], status=None),
            gates.provenance_gate([run.model_family], env=self.cfg.env),
        ]
        if self.cfg.verify_answers:
            results.append(gates.verifier_gate(verdict, independent_family=self.cfg.independent_verifier, sensitive=bool(flags)))
        decision = gates.decide(results, flags=flags)
        report = {**decision.report(), "retrieval": origins, "verifier_run_id": vrun_id, "context_hash": context_hash,
                  "verifier_pruned": pruned, "support_waived": support_waived}
        if decision.state != "machine_verified":
            return self._citations_only(base, context, ["requires_human_review"], sorted(flags), origins, run.id, report)
        sections = [{k: v for k, v in sec.items() if not k.startswith("_")} for sec in sections]
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
        if "requires_human_review" in warnings:
            short = ("התשובה לשאלה הזו נכתבה ומחכה לבדיקה של עורך האתר; אחרי האישור היא תופיע כאן ובעמוד \"שאלות ותשובות\". "
                     "בינתיים, אלה הקטעים הרלוונטיים מהפרוטוקולים:")
            note = "הבדיקה האוטומטית לא אישרה את כל המשפטים בתשובה, ולכן היא מחכה לעורך."
        else:
            short = "לא הצלחנו לנסח תשובה כרגע. אלה הקטעים הרלוונטיים מהפרוטוקולים, בלי פרשנות:"
            note = "אפשר לנסות לשאול שוב מאוחר יותר."
        env = self._envelope(**base, status="requires_human_review", short=short,
                             sections=[{"kind": "limitation", "text": note, "citation_ids": []}],
                             cited=units, warnings=warnings, review_state="human_review_required", flags=flags)
        # every passage the writer was given (not only the six shown): an editor's approval may cite any of them
        return AskResult(env, False, {**(report or {}), "retrieval": origins}, [c.unit.id for c in context], run_id)

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
        """Claim cards, then the published guides of the witnesses the question names, then the hearing digests that
        share the most words with it, then search — each layer with its own share, so search always has room
        (13.10.2026: a long question shared too few words with any digest, and a named witness's guide was never used)."""
        terms = set(query_terms(q))
        items: list[ContextItem] = []
        seen: set[str] = set()
        origins: dict[str, Any] = {"claim_cards": [], "witness_guides": [], "digests": [], "prosecution": 0, "court": 0,
                                   "party": 0, "defense": 0, "search": 0}

        def add(uid_list: list[str], bucket: str, origin: str, attribution: str | None = None, cap: int | None = None) -> int:
            units = self.store.public_units([u for u in uid_list if u not in seen])
            n = 0
            for uid in uid_list:
                if cap is not None and n >= cap:
                    break
                if uid in units and uid not in seen:
                    seen.add(uid)
                    items.append(ContextItem(units[uid], bucket, attribution, origin))
                    n += 1
            return n

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
            guides_fn = getattr(self.store, "published_witness_guides", None)
            room = self.cfg.guide_context
            for g in named_witnesses(q, guides_fn() if guides_fn else []):
                if room <= 0:
                    break
                origins["witness_guides"].append(g["object_id"])
                cids = [c for b in g["payload"].get("blocks", []) if b.get("block") == "testimony"
                        for it in b.get("items", []) for c in it.get("citation_ids", [])[:1]]
                room -= add(cids, "context", "witness_guide", cap=room)
            # a digest enters when it shares half the question's words — or, for a long question, at least three
            need = max(2, min(-(-len(terms) // 2), 3))
            scored = []
            for dg in self.store.published_digests():
                p = dg["payload"]
                d_terms = set(hebrew.search_terms(" ".join(p.get("topics", [])) + " " + p.get("summary", "")))
                shared = len(terms & d_terms)
                if shared >= need:
                    scored.append((shared, p.get("hearing_id") or dg.get("object_id"), p))
            room = self.cfg.digest_context
            for _shared, hid, p in sorted(scored, key=lambda x: (-x[0], str(x[1])))[:3]:
                if room <= 0:
                    break
                origins["digests"].append(hid)
                for sent in p.get("summary_sentences", []):
                    room -= add(sent["citation_ids"][:1], "context", "digest", cap=min(room, 1))
        if self._defense and self.cfg.prosecution_context > 0:
            origins["prosecution"] = self._prosecution_layer(q, add)
        if self._defense and self.cfg.documents_context > 0:
            origins["court"], origins["party"] = self._documents_layer(q, add)
        if self._defense and self.cfg.defense_context > 0:
            origins["defense"] = self._defense_layer(q, add)
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
        origins["roles"] = self._roles_layer(q, items, add) if self._defense else 0
        return items[:MAX_CONTEXT_DEFENSE if self._defense else MAX_CONTEXT_WITH_PAIRS], origins

    def _roles_layer(self, q: str, items: list, add) -> int:
        """Who the people in the answer are (17.10.2026: the verifier rejected "ראש צוות החקירה נצ"מ שלמה משולם" and
        "העוזרת האישית של מילצ'ן" because no cited passage said so): for witnesses named in the question or speaking in
        the context, the passage behind the first line of their guide's role block."""
        guides_fn = getattr(self.store, "published_witness_guides", None)
        if not guides_fn:
            return 0
        text = " ".join([q, *(c.unit.speaker_label or "" for c in items), *(c.unit.witness_label or "" for c in items)])
        cids: list[str] = []
        for g in named_witnesses(text, [g for g in guides_fn() if g.get("object_id")]):
            for b in g["payload"].get("blocks", []):
                if b.get("block") == "role" and b.get("items"):
                    cids.extend(b["items"][0].get("citation_ids", [])[:1])
                    break
            if len(cids) >= ROLE_CONTEXT:
                break
        return add(cids, "role", "witness_role", attribution="role")

    def _prosecution_layer(self, q: str, add) -> int:
        """The prosecution's claim from its own sources (16.10.2026: the "טענת התביעה" section was written from defense
        counsel's questions, failed the verifier and was dropped): the indictment's passages on the question's topic,
        and — when the question names a witness — the exchanges where the prosecution examined that witness."""
        from concurrent.futures import ThreadPoolExecutor

        n = self.cfg.prosecution_context
        reqs = [SearchRequest(q, SearchFilters(published_only=True, source_types=["indictment"]), limit=n)]
        guides_fn = getattr(self.store, "published_witness_guides", None)
        named = named_witnesses(q, guides_fn() if guides_fn else []) if guides_fn else []
        for g in named[:1]:
            name = re.sub(r"\([^)]*\)", " ", g["payload"].get("title") or "").strip()
            if name:
                topic = topic_query(q, name)
                reqs.append(SearchRequest(topic or name, SearchFilters(published_only=True, phase="direct", witness=name),
                                          limit=n * 3))
        with ThreadPoolExecutor(max_workers=len(reqs)) as ex:
            res = list(ex.map(self.search.search, reqs))
        indictment = [h.source_unit_id for h in res[0].hits
                      if {"exact", "terms", "graph"} & set(h.signals) or len(h.signals) >= 2][:n]
        total = add(indictment, "prosecution", "prosecution", attribution="indictment")
        if len(res) > 1:
            cand = [h.source_unit_id for h in res[1].hits]
            partners_fn = getattr(self.store, "exchange_partners", None)
            partners = partners_fn(cand) if partners_fn else {}
            views = self.store.public_units(list(dict.fromkeys([*cand, *partners.values()])))
            out: list[str] = []
            exchanges = 0
            for uid in cand:
                if exchanges >= n:
                    break
                u, p = views.get(uid), views.get(partners.get(uid) or "")
                if u is None or uid in out:
                    continue
                question = u if u.unit_type == "question" else p
                if question is None or question.speaker_role != "prosecution":
                    continue
                pair = [x.id for x in ([u, p] if u.unit_type == "question" else [p, u]) if x is not None]
                out.extend(x for x in pair if x not in out)
                exchanges += 1
            total += add(out, "prosecution", "prosecution", attribution="prosecution_direct_examination")
        return total

    def _documents_layer(self, q: str, add) -> tuple[int, int]:
        """Court decisions and the parties' filings on the question's topic (16.10.2026: the answer on the judges' call
        to drop the bribery charge cited counsel's description of it, not the court's decision of 29.6.2023, which ranked
        below the protocols in a plain search; the request for a pardon holds the defense's arguments in full)."""
        from concurrent.futures import ThreadPoolExecutor

        n = self.cfg.documents_context
        # the question as asked, and its subject alone: the decision of 29.6.2023 speaks of "קשיים בביסוס עבירת השוחד
        # שבאישום הראשון" — "מה המשמעות", "בתיק 4000" pushed it out of the first ten
        queries = list(dict.fromkeys(x for x in (q, focus_query(q)) if x))
        kinds = (DECISION_TYPES, PARTY_DOCUMENT_TYPES)
        reqs = [SearchRequest(x, SearchFilters(published_only=True, source_types=list(t)), limit=n * 2)
                for t in kinds for x in queries]
        with ThreadPoolExecutor(max_workers=len(reqs)) as ex:
            res = list(ex.map(self.search.search, reqs))

        def rel(group: list) -> list[str]:
            lists = [[h.source_unit_id for h in r.hits if {"exact", "terms", "graph"} & set(h.signals) or len(h.signals) >= 2]
                     for r in group]
            out: list[str] = []
            for rank in range(max((len(x) for x in lists), default=0)):  # interleaved: scores of searches do not compare
                for x in lists:
                    if rank < len(x) and x[rank] not in out:
                        out.append(x[rank])
            return out[:n]

        k = len(queries)
        court = add(rel(res[:k]), "court", "court_decision", attribution="court")
        party = add(rel(res[k:]), "party", "party_document", attribution="party_document")
        # a document the question names ("בקשת החנינה"): its own passages on the question's subject (17.10.2026: "מה
        # טוענת ההגנה בבקשת החנינה…" got five passages on the President's powers and found no argument)
        docs_fn = getattr(self.store, "published_documents", None)
        for d in named_documents(q, docs_fn() if docs_fn else [])[:2]:
            r = self.search.search(SearchRequest(focus_query(q) or q, SearchFilters(published_only=True,
                                                                                     source_version_ids=[d["id"]]),
                                                 limit=NAMED_DOCUMENT_CONTEXT * 2))
            hits = [h.source_unit_id for h in r.hits if {"exact", "terms", "graph"} & set(h.signals) or len(h.signals) >= 2]
            n_ = add(hits[:NAMED_DOCUMENT_CONTEXT], "court" if d.get("source_type") == "decision" else "party",
                     "named_document", attribution="court" if d.get("source_type") == "decision" else "party_document")
            if d.get("source_type") == "decision":
                court += n_
            else:
                party += n_
        return court, party

    def _defense_layer(self, q: str, add) -> int:
        """Passages from examinations conducted by defense counsel — the cross-examination of prosecution witnesses and
        the direct examination of the defense's witnesses — on the question's topic, each Q/A exchange kept whole.
        A broad question ('the champagne and cigars') otherwise draws mostly the prosecution's direct examination,
        where the allegation is phrased in the question's own words."""
        # a question that names a witness ("מה התברר בחקירה הנגדית של הדס קליין?") is answered from that witness's own
        # examination: their answers do not contain their name, so a plain search finds only places where counsel
        # mentions them in other examinations (13.10.2026). Witness-filtered probes: the question's topic, and each of
        # its words alone (in "כימות טובות ההנאה" the common phrase drowns the word that matters, 15.10.2026); with no
        # topic, what admissions sound like. Their results are interleaved (rank 1 of every probe, then rank 2 …),
        # because scores of different searches do not compare; then the topic searches by score.
        guides_fn = getattr(self.store, "published_witness_guides", None)
        named = named_witnesses(q, guides_fn() if guides_fn else []) if guides_fn else []
        witness_reqs: list[SearchRequest] = []
        for g in named[:2]:
            name = re.sub(r"\([^)]*\)", " ", g["payload"].get("title") or "").strip()
            if not name:
                continue
            topic = topic_query(q, name)
            terms = query_terms(topic) if topic else []
            probes = ([topic] if topic else []) + (terms[:3] if len(terms) > 1 else [])
            if len(terms) < 2:
                probes += list(ADMISSION_PROBES)
            for phase in ("cross", "direct"):
                witness_reqs += [SearchRequest(pq, SearchFilters(published_only=True, phase=phase, witness=name),
                                               limit=self.cfg.defense_context) for pq in dict.fromkeys(probes)]
        topic_reqs = [SearchRequest(q, SearchFilters(published_only=True, phase=phase), limit=self.cfg.defense_context * 2)
                      for phase in ("cross", "direct")]
        # each search takes a few seconds (n-gram and vector signals): run them side by side
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(8, len(witness_reqs) + len(topic_reqs))) as ex:
            responses = list(ex.map(self.search.search, witness_reqs + topic_reqs))
        w_lists = [r.hits for r in responses[:len(witness_reqs)]]
        cand: list[str] = []
        for rank in range(max((len(x) for x in w_lists), default=0)):
            for lst in w_lists:
                if rank < len(lst) and lst[rank].source_unit_id not in cand:
                    cand.append(lst[rank].source_unit_id)
        topic_hits = [h for r in responses[len(witness_reqs):] for h in r.hits
                      if {"exact", "terms", "graph"} & set(h.signals) or len(h.signals) >= 2]
        for h in sorted(topic_hits, key=lambda h: -h.score):
            if h.source_unit_id not in cand:
                cand.append(h.source_unit_id)
        partners_fn = getattr(self.store, "exchange_partners", None)
        partners = partners_fn(cand) if partners_fn else {}
        views = self.store.public_units(list(dict.fromkeys([*cand, *partners.values()])))

        def asked_by_defense(uid: str) -> bool:
            u = views.get(uid)
            if u is None:
                return False
            if u.speaker_role in DEFENSE_ROLES:
                return True
            p = views.get(partners.get(uid) or "")
            return p is not None and p.unit_type == "question" and p.speaker_role in DEFENSE_ROLES

        pairs: list[list[str]] = []
        taken: set[str] = set()
        for uid in cand:
            if len(pairs) >= self.cfg.defense_context:
                break
            if not asked_by_defense(uid) or uid in taken:
                continue
            p = partners.get(uid)
            u = views[uid]
            pair = ([uid, p] if u.unit_type == "question" else [p, uid]) if p and p in views else [uid]
            pair = [x for x in pair if x not in taken]
            taken.update(pair)
            pairs.append(pair)
        # the passages just before and after the strongest exchanges, so the writer knows what each one is about
        # (16.10.2026: "she left the phones at home" meant nothing without the question that led to it)
        around_fn = getattr(self.store, "surrounding", None)
        top = pairs[:self.cfg.surround_exchanges]
        around = around_fn([x for pr in top for x in (pr[0], pr[-1])], before=2, after=2) if around_fn and top else {}
        n = 0
        for i, pair in enumerate(pairs):
            if i < len(top):
                n += add(around.get(pair[0], ([], []))[0], "surrounding", "defense", attribution="surrounding_passage")
            n += add(pair, "defense", "defense", attribution="defense_examination")
            if i < len(top):
                n += add(around.get(pair[-1], ([], []))[1], "surrounding", "defense", attribution="surrounding_passage")
        return n


# witnesses who are also defendants are named in almost every question: their guide enters only by full name
DEFENDANT_FAMILY_NAMES = frozenset({"נתניהו", "אלוביץ", "מוזס"})


def named_witnesses(q: str, guides_: list[dict]) -> list[dict]:
    """Published witness guides whose person the question names: the full name, or a family name that points to one
    witness (never a defendant's family name alone)."""
    from .guides import name_matches

    t = " " + hebrew.normalize(q).replace("'", "").replace("׳", "") + " "

    def parts(name: str) -> list[str]:
        clean = re.sub(r"\([^)]*\)", " ", hebrew.normalize(name)).replace("'", "").replace("׳", "")
        return [x for x in re.split(r"[\s-]+", clean) if len(x) > 1]

    def days(g: dict) -> int:
        return len(g["payload"].get("source_version_ids") or [])

    family: dict[str, list[dict]] = {}
    for g in guides_:
        ps = parts(g["payload"].get("title") or "")
        if ps:
            family.setdefault(ps[-1], []).append(g)

    def by_family(g: dict, fam: str) -> bool:
        """The family name alone points to this witness: the only one, or one who testified at least twice as long."""
        others = sorted((days(x) for x in family.get(fam, []) if x is not g), reverse=True)
        return not others or days(g) >= 2 * max(1, others[0])
    out = []
    for g in guides_:
        name = g["payload"].get("title") or ""
        ps = parts(name)
        if not ps or not name_matches(name, q):
            continue
        full = all(re.search(rf"(?<![א-ת]){re.escape(x)}(?![א-ת])", t) for x in ps)
        unique = by_family(g, ps[-1]) and not any(ps[-1].startswith(hebrew.normalize(d)) for d in DEFENDANT_FAMILY_NAMES)
        if full or unique:
            out.append(g)
    return out[:3]


MAX_CONTEXT_WITH_PAIRS = 32

# what admissions sound like in a cross-examination, for a question that names a witness and no topic
ADMISSION_PROBES = ("נכון שאמרת", "אישרת", "לא זוכרת", "בהודעה שלך במשטרה", "סותר את מה שאמרת")
# words that ask about an examination rather than name its topic
META_WORDS = frozenset({"התברר", "התבררו", "עלה", "עלו", "העיד", "העידה", "העידו", "חקירה", "בחקירה", "החקירה",
                        "נגדית", "הנגדית", "ראשית", "הראשית", "עדות", "עדותו", "עדותה", "בעדותו", "בעדותה", "אמר",
                        "אמרה", "סיפר", "סיפרה", "נאמר", "קרה", "מה", "על"})


# words that frame a question rather than name its subject, and case numbers, which documents rarely repeat
FRAME_WORDS = frozenset({"מה", "מהי", "מהו", "המשמעות", "משמעות", "של", "על", "האם", "איך", "כיצד", "למה", "מדוע", "מי",
                         "שעליהם", "שעליהן", "שעליו", "שעליה", "עליהם", "הצביעו", "הצביע", "הצביעה", "ביחס", "לגבי",
                         "בנוגע", "בעניין", "בתיק", "תיק", "בפרשת", "פרשת", "אמרו", "אמר", "אמרה", "היה", "היו", "יש"})


# words too common in document titles to name one
TITLE_STOP = frozenset({"החלטה", "החלטת", "בקשה", "בקשת", "תגובה", "תגובת", "הודעה", "הודעת", "מסמך", "עתירה", "מטעם",
                        "נאשם", "נאשמים", "המאשימה", "מאשימה", "בית", "משפט", "המשפט", "תיק", "דיון", "פרוטוקול", "לפי",
                        "סעיף", "בעניין", "על", "של", "את", "עם", "לא", "כי", "גם", "או", "בין", "תיקימ", "התיקימ",
                        "תיקים", "התיקים", "ראיות", "הראיות", "הגנה", "ההגנה", "תביעה", "התביעה", "שופט",
                        "השופט", "השופטת", "שופטים", "השופטים", "שופטימ", "השופטימ"})


DOC_NOUNS = re.compile(r"(?<![א-ת])[ובלמה]?(?:בקשת|בקשה|החלטת|החלטה|תגובת|תגובה|הודעת|הודעה|מכתב|עתירת|עתירה|מזכר|תצהיר|חוות\s+דעת)"
                       r"\s+([א-ת\"']+)(?:\s+([א-ת\"']+))?")


def named_documents(q: str, docs: list[dict]) -> list[dict]:
    """Documents the question names: a document word and what follows it ("בבקשת החנינה", "החלטת השופטים"), matched to a
    word of a title that at most two titles share."""
    named: set[str] = set()
    for m in DOC_NOUNS.finditer(hebrew.normalize(q)):
        for w in m.groups():
            if w:
                named |= {t for t in hebrew.search_terms(w) if len(t) > 2 and t not in TITLE_STOP}
    if not named or not docs:
        return []
    titles = [(d, {t for t in hebrew.search_terms(d.get("title") or "") if len(t) > 2 and t not in TITLE_STOP
                   and not t.isdigit()}) for d in docs]
    freq: dict[str, int] = {}
    for _d, ts in titles:
        for t in ts:
            freq[t] = freq.get(t, 0) + 1
    scored = []
    for d, ts in titles:
        weight = sum(1 / freq[t] for t in ts & named if freq.get(t, 0) <= 2)
        if weight >= 0.5:
            scored.append((-weight, d.get("id") or "", d))
    return [x[2] for x in sorted(scored, key=lambda x: x[:2])]


def focus_query(q: str) -> str:
    """The subject of a question without its framing ("מה המשמעות של…", "בתיק 4000"), for searching documents."""
    words = [w for w in re.findall(r"[א-ת0-9\"]+", hebrew.normalize(q).replace("'", "").replace("׳", ""))
             if w not in FRAME_WORDS and not re.fullmatch(r"\d{4}", w)]
    rest = " ".join(words)
    return rest if len(words) >= 2 and query_terms(rest) else ""


def topic_query(q: str, name: str) -> str:
    """The question without the witness's name and the words that only ask about the examination."""
    t = hebrew.normalize(q).replace("'", "").replace("׳", "")
    for part in re.split(r"[\s-]+", hebrew.normalize(name).replace("'", "")):
        if len(part) > 1:
            t = re.sub(rf"(?<![א-ת])[ובלמשה]?{re.escape(part)}(?![א-ת])", " ", t)
    words = [w for w in re.findall(r"[א-ת0-9\"]+", t) if w not in META_WORDS and w.lstrip("ו") not in META_WORDS]
    rest = " ".join(words)
    return rest if query_terms(rest) else ""


def move_inline_ids(text: str, citation_ids: list[str], allowed: set[str]) -> tuple[str, list[str]]:
    """Passage ids the writer put in the prose: known ones join the citations, all of them leave the text."""
    from .editorial import UNIT_ID, strip_unit_ids

    found = [x for x in re.findall(UNIT_ID, text or "") if x in allowed]
    ids_ = list(dict.fromkeys([*citation_ids, *found]))
    return strip_unit_ids(text), ids_
# 16.10.2026: the findings are paragraphs now (2-5 of them), not 4-10 one-line points: one approved paragraph, with
# the summary and the significance, still answers the question
MIN_DEFENSE_POINTS_AFTER_PRUNING = 1

_ATTRIBUTED = re.compile(
    r"(?:לטענת|לשיטת|לדברי|לגישת|לעמדת)\s+(?:ה)?(?:הגנה|סנגור|סנגוריה|תביעה|מאשימה|פרקליטות)"
    r"|(?:ה)?(?:הגנה|סנגוריה|תביעה|מאשימה|פרקליטות)\s+(?:טוענ|טען|סבור|מבקש|הדגיש|ציינ|הציג)"
    r"|עו\"?ד\s+\S+\s+\S*\s*(?:טען|הדגיש|ציין|הציג|הטיח)")


_ALLEGED = re.compile(r"(?:כתב\s*ה?אישום|התביעה|המאשימה|הפרקליטות)\s*(?:טוע|טען|מייחס|ייחס|גורס)|לפי\s*כתב\s*ה?אישום"
                      r"|לפי\s*הנטען|נטען\s*כי|לטענת\s*(?:ה)?(?:תביעה|מאשימה|פרקליטות)|מיוחס(?:ת)?\s*ל")


def answer_flags(a) -> set[str]:
    """Risk flags of one sentence. "קיבל שוחד" or "הרשעה" in the indictment's allegation or in a party's argument is
    that party's claim, not the site's conclusion (17.10.2026: "כתב האישום טוען כי נתניהו קיבל שוחד…" held an answer
    the verifier fully approved)."""
    flags = set(gates.risk_flags(a.text))
    if "final_legal_conclusion" in flags and (getattr(a, "kind", None) in {"allegation", "prosecution"}
                                              or attributed_argument(a) or _ALLEGED.search(a.text or "")):
        flags.discard("final_legal_conclusion")
    return flags


def attributed_argument(a) -> bool:
    """A section that is a party's argument by construction (significance) or says whose argument it is: 'proof' or
    'proven' there is that party's word, not the site's (16.10.2026: 'ההגנה סבורה כי בהיעדר הוכחה…' was rejected)."""
    return a.kind == "significance" or bool(_ATTRIBUTED.search(a.text or ""))


def verifier_approved(verifier: dict) -> set[str]:
    """Paths the verifier fully approved: supported, correctly attributed, no overstatement, no false premise."""
    return {x.get("path") for x in verifier.get("assertions", [])
            if x.get("supported") == "yes" and x.get("attribution_ok", True)
            and not x.get("judicial_overstatement") and not x.get("false_premise")}


def prune_unapproved(sections: list[dict], verifier: dict) -> tuple[list[dict], list[dict], dict | None] | None:
    """13.10.2026, the same policy as the witness guides ('publish what is right, hold only what is not'): when the
    verifier fails some of an answer's sections (not fully supported, misattributed, a judicial overstatement, a false
    premise), those sections are dropped and the rest is published. When it fails the short answer (16.10.2026: a
    summary saying 'it came out that…' where counsel had only put it to the witness), the strongest approved defense
    point — the first — becomes the short answer. Held: when the verifier found material in the bundle that
    contradicts the text, or when fewer than two of the defense's points would remain. Returns (kept sections, what
    was dropped, the new short answer or None) or None."""
    if verifier.get("omitted_counterevidence"):
        return None
    bad = {x.get("path"): x for x in verifier.get("assertions", [])
           if x.get("supported") != "yes" or not x.get("attribution_ok", True)
           or x.get("judicial_overstatement") or x.get("false_premise")}
    if not bad:
        return None
    kept, dropped = [], []
    for i, s in enumerate(sections):
        x = bad.get(f"sections/{i}")
        if x is not None and s["kind"] != "limitation":
            dropped.append({"path": f"sections/{i}", "kind": s["kind"], "text": s["text"], "note": x.get("note"),
                            "supported": x.get("supported"), "attribution_ok": x.get("attribution_ok", True)})
        else:
            kept.append(s)
    short = None
    if "answer_short" in bad:
        x = bad["answer_short"]
        first = next((s for s in kept if s["kind"] == "defense"), None)
        if first is None:
            return None
        kept = [s for s in kept if s is not first]
        short = {"text": first["text"], "citation_ids": list(first["citation_ids"]), "_vpath": first.get("_vpath")}
        dropped.append({"path": "answer_short", "kind": "answer_short", "text": None, "note": x.get("note"),
                        "supported": x.get("supported"), "attribution_ok": x.get("attribution_ok", True)})
    if sum(1 for s in kept if s["kind"] == "defense") < MIN_DEFENSE_POINTS_AFTER_PRUNING:
        return None
    return kept, dropped, short


ROLE_CONTEXT = 8
NAMED_DOCUMENT_CONTEXT = 10
DECISION_TYPES = ("decision",)
PARTY_DOCUMENT_TYPES = ("motion", "response", "notice", "affidavit", "other")
MAX_CONTEXT_DEFENSE = 140  # the defense layer: up to 2 × defense_context units, 4 around each of the top exchanges
DEFENSE_ROLES = frozenset({"defense", "defendant"})


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
