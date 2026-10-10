"""Q/A pairing and answer-relation classification (spec §23.3, §27.3).

Rules run before any model:
* a question pairs with the next answer of the same examination;
* the witness of the answer must be the examination witness;
* an intervening turn (objection, judge's remark) breaks the pair unless it
  is short and the distance is within ``MAX_INTERVENING``; such pairs are
  flagged ``interrupted`` and get lower confidence;
* an answer of "כן" does not make the whole question the witness's
  testimony: the stored ``interpreted_proposition`` is the question text,
  attributed as "affirmed in counsel's question", and public wording is
  produced only for ``affirms`` after verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import ids
from .protocol import PARSER_VERSION, UnitRecord

PAIRER_VERSION = "qa-pairer-1.0"
MAX_INTERVENING = 2
MAX_INTERVENING_WORDS = 30

_AFFIRM = r"(?:כן|נכון|נכון מאוד|בדיוק|בהחלט|אכן|מאשר|מאשרת|ודאי|בוודאי|כמובן|נכון,? כן|כן,? נכון|זה נכון|נכון מאד|אמת)"
_DENY = r"(?:לא|לא נכון|ממש לא|בשום פנים|אף פעם|מעולם לא|שולל|שוללת|זה לא נכון|לא היה דבר כזה|ממש לא נכון|בשום אופן לא)"
_DKNOW = (
    r"(?:אני\s+)?(?:לא\s+זוכר|לא\s+זוכרת|אינני\s+זוכר|אינני\s+זוכרת|לא\s+זכור\s+לי|לא\s+יודע|לא\s+יודעת|אינני\s+יודע"
    r"|אינני\s+יודעת|אין\s+לי\s+מושג|לא\s+יכול\s+לומר|לא\s+יכולה\s+לומר|לא\s+יכול\s+לזכור|לא\s+ידוע\s+לי|לא\s+זוכר\s+את\s+זה)"
)
_QUALIFIERS = re.compile(
    r"\b(?:אבל|אך|רק|למעט|בערך|בגדול|פחות או יותר|לא בדיוק|במידה מסוימת|יכול להיות|ייתכן|יתכן|נדמה לי|אני חושב|אני חושבת"
    r"|למיטב זכרוני|למיטב ידיעתי|בהסתייגות|חלקית|לא תמיד|לפעמים|בחלק|זה תלוי|אני מניח|אני מניחה|כנראה|אולי)\b"
)
_NONRESP = re.compile(
    r"^(?:מה\s+זאת\s+אומרת|לא\s+הבנתי|אני\s+לא\s+מבין|אני\s+לא\s+מבינה|על\s+מה\s+אתה\s+מדבר|איזו?\s+שאלה|אפשר\s+לחזור\s+על\s+השאלה)"
)
_OPEN_Q = re.compile(r"^ו?(?:מה|מי|איך|כיצד|למה|מדוע|מתי|איפה|היכן|כמה|תאר|תארי|ספר|ספרי|הסבר|הסבירי|באיזה|באילו|מאיפה|לאן|על מה)\b")


@dataclass
class Exchange:
    id: str
    question: UnitRecord
    answer: UnitRecord
    phase: str
    asker_label: str | None
    asker_side: str | None
    witness_label: str | None
    answer_relation: str
    confidence: float
    interpreted_proposition: str | None
    public_wording: str | None
    flags: list[str] = field(default_factory=list)
    rule: str = ""


def _head(text: str, words: int = 6) -> str:
    t = re.sub(r"[\"'״׳()]", "", text).strip()
    return " ".join(t.split()[:words])


def _is_open_question(question: str) -> bool:
    sentences = [x.strip() for x in re.split(r"(?<=[.?!])\s+", question.strip()) if x.strip()]
    last = sentences[-1] if sentences else question
    return bool(_OPEN_Q.match(last.strip()))


def classify_answer(question: str, answer: str) -> tuple[str, float, str]:
    """Return (relation, confidence, rule) using lexical rules only."""
    a = re.sub(r"\s+", " ", answer).strip()
    a_low = a.strip(" .,!?")
    words = a_low.split()
    head = _head(a_low)
    if not a_low:
        return "nonresponsive", 0.6, "empty"
    if _NONRESP.match(a_low) or (a_low.endswith("?") and len(words) <= 8):
        return "nonresponsive", 0.85, "question_back"
    if re.match(rf"^{_DKNOW}\b", head):
        return "does_not_know", 0.92, "dont_know"
    if re.match(rf"^{_AFFIRM}(?:[\s.,!]|$)", a_low):
        rest = re.sub(rf"^{_AFFIRM}[\s.,!]*", "", a_low)
        if not rest:
            return "affirms", 0.95, "bare_affirmation"
        if _QUALIFIERS.search(rest) or re.match(r"^(?:אבל|אך|רק)\b", rest):
            return "qualified_affirmation", 0.85, "affirmation_with_qualifier"
        if len(rest.split()) > 25:
            return "qualified_affirmation", 0.6, "affirmation_with_long_explanation"
        return "affirms", 0.8, "affirmation_with_restatement"
    if re.match(rf"^{_DENY}(?:[\s.,!]|$)", a_low) and not re.match(rf"^{_DKNOW}", a_low):
        rest = re.sub(rf"^{_DENY}[\s.,!]*", "", a_low)
        if _QUALIFIERS.search(rest):
            return "ambiguous", 0.55, "denial_with_qualifier"
        return "denies", 0.9 if len(words) <= 6 else 0.75, "denial"
    if _is_open_question(question):
        return "ambiguous", 0.7, "narrative_answer_to_open_question"
    if _QUALIFIERS.search(" ".join(words[:8])) and len(words) <= 12:
        return "qualified_affirmation", 0.5, "hedge_only"
    return "ambiguous", 0.5, "unclassified"


def _asker_phrase(side: str | None, female: bool = False) -> str:
    if side == "prosecution":
        return "בשאלת ב״כ המאשימה"
    if side and side.startswith("defense"):
        return "בשאלת ב״כ ההגנה"
    return "בשאלה שהוצגה לה" if female else "בשאלה שהוצגה לו"


def pair_exchanges(units: list[UnitRecord], *, parser_version: str = PARSER_VERSION) -> tuple[list[Exchange], list[str]]:
    exchanges: list[Exchange] = []
    warnings: list[str] = []
    # only first part of each turn participates; continuation parts belong to it
    firsts = [u for u in units if u.turn_part == 0]
    texts: dict[str, str] = {}
    for u in units:
        texts[u.turn_key] = (texts.get(u.turn_key, "") + "\n" + u.raw_text).strip()
    i = 0
    while i < len(firsts):
        q = firsts[i]
        if q.unit_type != "question":
            i += 1
            continue
        j = i + 1
        intervening = 0
        interrupted = False
        paired = False
        while j < len(firsts) and intervening <= MAX_INTERVENING:
            nxt = firsts[j]
            if nxt.unit_type == "answer":
                if nxt.witness_label != q.witness_label or (
                    nxt.examination_phase != q.examination_phase and "court_questions" not in {nxt.examination_phase, q.examination_phase}
                ):
                    warnings.append(f"answer {nxt.id} does not match question {q.id} witness/phase")
                    break
                qtext, atext = texts[q.turn_key], texts[nxt.turn_key]
                relation, conf, rule = classify_answer(qtext, atext)
                flags = []
                if interrupted:
                    conf = max(0.0, conf - 0.15)
                    flags.append("interrupted")
                if "asker_unknown" in q.flags:
                    conf = max(0.0, conf - 0.2)
                    flags.append("asker_unknown")
                proposition = qtext if relation in {"affirms", "qualified_affirmation", "denies"} else None
                wording = None
                female = bool(q.witness_label and q.witness_label.startswith(("העדה", "עדת")))
                if relation == "affirms" and not flags:
                    verb = "העדה אישרה" if female else "העד אישר"
                    wording = f"{verb} את הנטען {_asker_phrase(q.speaker_side, female)}"
                elif relation == "denies" and not flags:
                    verb = "העדה הכחישה" if female else "העד הכחיש"
                    wording = f"{verb} את הנטען {_asker_phrase(q.speaker_side, female)}"
                exchanges.append(
                    Exchange(
                        id=ids.exchange_id(q.id, nxt.id, parser_version),
                        question=q,
                        answer=nxt,
                        phase=q.examination_phase,
                        asker_label=q.speaker_label,
                        asker_side=q.speaker_side,
                        witness_label=q.witness_label,
                        answer_relation=relation,
                        confidence=round(conf, 3),
                        interpreted_proposition=proposition,
                        public_wording=wording,
                        flags=flags,
                        rule=rule,
                    )
                )
                paired = True
                break
            if nxt.unit_type == "question":
                break  # unanswered question
            words = len(texts[nxt.turn_key].split())
            if nxt.speaker_role in {"judge", "court"} or words > MAX_INTERVENING_WORDS:
                break  # judge's remark or long intervention breaks the sequence (spec §27.3)
            intervening += 1
            interrupted = True
            j += 1
        i = j if paired else i + 1
    return exchanges, warnings
