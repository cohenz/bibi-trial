"""Structural parser for Hebrew court protocols (spec §27.2–27.3).

Input: body lines with page/line numbers. Output: header metadata, speech
turns and SourceUnits (one per turn per page).

The parser never depends on the *search* normaliser: it uses its own pinned
view of the text (``_pv``) so that changes to search normalisation do not
change segmentation or SourceUnit identifiers (spec §27.4).

Speaker model
-------------
* explicit speaker lines ``<label>: text`` set the current speaker;
* ``ש.``/``ש:`` and ``ת.``/``ת:`` only have meaning inside an examination
  state where the asker and the witness are known (spec §27.3). Outside an
  examination they are kept as text of the current speaker and flagged;
* witness introductions ("העד ... לאחר שהוזהר ... משיב לשאלות עו"ד X") and
  examination headings ("חקירה נגדית ע"י עו"ד X") set witness, phase and
  asker.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .. import ids
from .pdf import Line

PARSER_VERSION = "protocol-parser-1.0"

# ---------------------------------------------------------------------------
# pinned text view used for structure detection only
# ---------------------------------------------------------------------------
_BIDI = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"), None)


def _pv(text: str) -> str:
    s = unicodedata.normalize("NFC", text).translate(_BIDI)
    s = s.replace("״", '"').replace("”", '"').replace("“", '"').replace("׳", "'").replace("’", "'").replace("`", "'")
    s = re.sub(r"<#\d+#>", " ", s)  # Net-HaMishpat page anchors
    return re.sub(r"\s+", " ", s).strip()


def clean_line_text(text: str) -> str:
    """Raw text for storage: only anchors and bidi controls removed."""
    s = unicodedata.normalize("NFC", text).translate(_BIDI)
    s = re.sub(r"<#\d+#>", " ", s)
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------
HONORIFICS = r"(?:כב'\s*)?(?:השופטת|השופט|אב\"ד)"
COUNSEL = r"(?:עו\"ד|עוה\"ד|ב\"כ)"
SPEAKER_PREFIXES = (
    r"עו\"ד|עוה\"ד|ב\"כ|כב'|השופטת|השופט|אב\"ד|העד|העדה|הנאשם|הנאשמת|נאשם|נאשמת|מר|גב'|ד\"ר|פרופ'|רו\"ח"
    r"|המתורגמן|המתורגמנית|התובע|התובעת|הסנגור|הסניגור|הסנגורית|המאשימה|ההגנה|דובר|דוברת|קלדנית|רשמת"
)
SPEAKER_RE = re.compile(rf"^(?P<label>(?:{SPEAKER_PREFIXES})[^:]{{0,60}}?)\s*:\s*(?P<rest>.*)$")
Q_RE = re.compile(r"^ש\s*[.:\-–]\s*(?P<rest>.*)$")
A_RE = re.compile(r"^ת\s*[.:\-–]\s*(?P<rest>.*)$")
INLINE_A_RE = re.compile(r"(?<=[?.!״\"])\s+ת\s*[.:]\s+")
CASE_NO_RE = re.compile(r"\b(\d{4,5}-\d{2}-\d{2})\b")
HEB_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6, "יולי": 7,
    "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}
DATE_WORDS_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(HEB_MONTHS) + r")\s+(\d{4})\b")
DATE_NUM_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
PROTOCOL_HEADING_RE = re.compile(r"^פרוטוקול$")
ATTENDANCE_RE = re.compile(r"^נוכחים\s*:?(?P<rest>.*)$")
PHASE_WORDS = {
    "ראשית": "direct",
    "נגדית": "cross",
    "חוזרת": "redirect",
}
PHASE_HEADING_RE = re.compile(
    rf"^(?:המשך\s+)?חקירה\s+(?P<phase>ראשית|נגדית|חוזרת)(?:\s+(?:נוספת|חוזרת))?"
    rf"(?:\s*(?:ע\"י|על ידי|של|מטעם)\s*(?P<asker>{COUNSEL}\s*[^:,]{{2,40}}))?\s*:?\s*$"
)
WITNESS_INTRO_RE = re.compile(
    r"^(?P<role>העד|העדה|עד התביעה|עדת התביעה|עד ההגנה|עדת ההגנה)\s*[,:]?\s*(?P<name>[^,]{2,60}?)\s*,?\s*"
    r"(?:לאחר\s+שהוזהר(?:ה)?|מוזהר(?:ת)?|לאחר\s+שהצהיר(?:ה)?)"
)
INTRO_PHASE_RE = re.compile(r"(?:ב)?חקירה\s+(?P<phase>ראשית|נגדית|חוזרת)")
INTRO_ASKER_RE = re.compile(r"(?:לשאלות|ע\"י|על ידי|של)\s*(?P<asker>" + COUNSEL + r"\s*[^\s,:.]+(?:\s+(?!בחקירה|חקירה)[^\s,:.]+)?)")
COURT_DECISION_RE = re.compile(r"^(?:החלטה|ה\s*ח\s*ל\s*ט\s*ה)\s*:?\s*$")
INTERRUPTION_RE = re.compile(r"^\((?P<note>[^)]{1,120})\)$")
PROSECUTION_RE = re.compile(r"(?:ב\"כ\s+)?(?:המאשימה|התביעה|הפרקליטות|מדינת ישראל)")
DEFENSE_RE = re.compile(r"(?:ב\"כ\s+)?(?:הנאשם|הנאשמת|הנאשמים|הסנגור|ההגנה)\s*(?P<num>\d)?")


@dataclass
class Speaker:
    label: str
    role: str  # judge | prosecution | defense | witness | defendant | court | other | unknown
    side: str | None = None  # prosecution | defense_1 | defense_2 | defense_3 | court | witness | None
    entity_key: str | None = None


@dataclass
class Turn:
    key: str
    speaker: Speaker | None
    unit_type: str  # speech_turn | question | answer | decision | caption | other
    phase: str
    lines: list[Line] = field(default_factory=list)
    witness: str | None = None
    flags: list[str] = field(default_factory=list)

    def text_by_page(self) -> list[tuple[int, list[Line]]]:
        out: list[tuple[int, list[Line]]] = []
        for ln in self.lines:
            if out and out[-1][0] == ln.page:
                out[-1][1].append(ln)
            else:
                out.append((ln.page, [ln]))
        return out


@dataclass
class ProtocolHeader:
    court_case_number: str | None = None
    hearing_date: str | None = None
    court_name: str | None = None
    judges: list[str] = field(default_factory=list)
    attendees: list[tuple[str, str]] = field(default_factory=list)  # (label, side)
    header_end_index: int = 0


@dataclass
class UnitRecord:
    id: str
    ordinal: int
    page: int
    line_start: int
    line_end: int
    speaker_label: str | None
    speaker_role: str | None
    speaker_side: str | None
    unit_type: str
    examination_phase: str
    raw_text: str
    turn_key: str
    turn_part: int
    witness_label: str | None
    synthetic_lines: bool
    flags: list[str] = field(default_factory=list)


@dataclass
class ParsedProtocol:
    header: ProtocolHeader
    turns: list[Turn]
    units: list[UnitRecord]
    witnesses: list[str]
    warnings: list[str]
    parser_version: str = PARSER_VERSION


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _surname(label: str) -> str:
    s = re.sub(rf"^(?:{SPEAKER_PREFIXES})\s*", "", _pv(label)).strip()
    s = re.sub(r"^(?:השופטת|השופט)\s*", "", s).strip()
    s = re.sub(r",.*$", "", s)
    parts = s.split()
    return parts[-1] if parts else s


def _speaker_key(label: str) -> str:
    return ids.normalize_speaker_label(_pv(label))


def parse_date(text: str) -> str | None:
    t = _pv(text)
    m = DATE_WORDS_RE.search(t)
    if m:
        d, mon, y = int(m.group(1)), HEB_MONTHS[m.group(2)], int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}"
    m = DATE_NUM_RE.search(t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


class SpeakerDirectory:
    """Maps labels to roles and sides using the attendance list and the bench."""

    def __init__(self, header: ProtocolHeader):
        self.judges = {_surname(j) for j in header.judges if _surname(j)}
        self.sides: dict[str, str] = {}
        for label, side in header.attendees:
            sn = _surname(label)
            if sn:
                self.sides[sn] = side

    def classify(self, label: str, witness: str | None) -> Speaker:
        lab = _pv(label)
        sn = _surname(lab)
        if re.match(r"^(?:העד|העדה|עד התביעה|עדת התביעה|עד ההגנה|עדת ההגנה)\b", lab):
            return Speaker(label=label, role="witness", side="witness", entity_key=_speaker_key(witness or label))
        if re.match(r"^(?:כב'|השופט|השופטת|אב\"ד)", lab):
            return Speaker(label=label, role="judge", side="court", entity_key=_speaker_key(label))
        if re.match(r"^(?:הנאשם|הנאשמת|נאשם|נאשמת)", lab):
            return Speaker(label=label, role="defendant", side="defense", entity_key=_speaker_key(label))
        if re.match(rf"^{COUNSEL}", lab) or re.match(r"^(?:התובע|התובעת|הסנגור|הסניגור|הסנגורית)", lab):
            side = self.sides.get(sn)
            if side is None:
                if re.match(r"^(?:התובע|התובעת)", lab):
                    side = "prosecution"
                elif re.match(r"^(?:הסנגור|הסניגור|הסנגורית)", lab):
                    side = "defense"
            role = "prosecution" if side == "prosecution" else ("defense" if side and side.startswith("defense") else "counsel")
            return Speaker(label=label, role=role, side=side, entity_key=_speaker_key(label))
        if re.match(r"^(?:המתורגמן|המתורגמנית)", lab):
            return Speaker(label=label, role="interpreter", side=None, entity_key=_speaker_key(label))
        # bare names: witness surname match first, then the bench
        if witness and sn and sn == _surname(witness):
            return Speaker(label=label, role="witness", side="witness", entity_key=_speaker_key(witness))
        if sn in self.judges:
            return Speaker(label=label, role="judge", side="court", entity_key=_speaker_key(label))
        return Speaker(label=label, role="other", side=self.sides.get(sn), entity_key=_speaker_key(label))


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------

def parse_header(lines: list[Line], max_scan: int = 80) -> ProtocolHeader:
    h = ProtocolHeader()
    attendance_mode = False
    current_side: str | None = None
    for i, ln in enumerate(lines[:max_scan]):
        t = _pv(ln.text)
        if not t:
            continue
        if h.court_case_number is None:
            m = CASE_NO_RE.search(t)
            if m:
                h.court_case_number = m.group(1)
        if h.hearing_date is None:
            d = parse_date(t)
            if d:
                h.hearing_date = d
        if h.court_name is None and t.startswith("בית המשפט"):
            h.court_name = t
        if re.search(r"(?:כב'\s*)?(?:השופטת|השופט)\s+\S+", t) and not SPEAKER_RE.match(t) and not attendance_mode:
            for m in re.finditer(r"(?:כב'\s*)?(?:השופטת|השופט)\s+([^,]+?)(?:,|$|\s+אב\"ד|\s+-\s+)", t):
                name = m.group(1).strip()
                if name and name not in h.judges:
                    h.judges.append(name)
        m = ATTENDANCE_RE.match(t)
        if m:
            attendance_mode = True
            t = m.group("rest").strip()
            if not t:
                continue
        if PROTOCOL_HEADING_RE.match(t):
            h.header_end_index = i + 1
            return h
        if attendance_mode:
            if PROSECUTION_RE.search(t) and ("ב\"כ" in t or "המאשימה" in t):
                current_side = "prosecution"
            dm = DEFENSE_RE.search(t)
            if dm and ("ב\"כ" in t or "הנאשם" in t):
                current_side = f"defense_{dm.group('num')}" if dm.group("num") else "defense"
            for cm in re.finditer(rf"({COUNSEL}\s*[^,;:]+?)(?=,|;|$|\s+{COUNSEL})", t):
                label = cm.group(1).strip()
                if current_side and label:
                    h.attendees.append((label, current_side))
    # no explicit "פרוטוקול" heading: header ends at first speaker line
    for i, ln in enumerate(lines[:max_scan]):
        if SPEAKER_RE.match(_pv(ln.text)):
            h.header_end_index = i
            break
    return h


# ---------------------------------------------------------------------------
# turns
# ---------------------------------------------------------------------------

def parse_protocol(lines: list[Line], *, source_version_id: str, case_number_hint: str | None = None) -> ParsedProtocol:
    body = [ln for ln in lines if ln.kind == "body" and ln.text.strip()]
    header = parse_header(body)
    if not header.court_case_number:
        for ln in lines[:200]:
            m = CASE_NO_RE.search(_pv(ln.text))
            if m:
                header.court_case_number = m.group(1)
                break
    if case_number_hint and not header.court_case_number:
        header.court_case_number = case_number_hint
    directory = SpeakerDirectory(header)
    warnings: list[str] = []

    turns: list[Turn] = []
    witnesses: list[str] = []
    state = {"phase": "preliminary", "asker": None, "witness": None, "speaker": None}

    def new_turn(speaker: Speaker | None, unit_type: str, first: Line, flags: list[str] | None = None) -> Turn:
        t = Turn(
            key=f"t{len(turns):05d}",
            speaker=speaker,
            unit_type=unit_type,
            phase=state["phase"],
            witness=state["witness"],
            flags=list(flags or []),
        )
        t.lines.append(first)
        turns.append(t)
        return t

    def add_text(turn: Turn, ln: Line, text: str) -> None:
        if turn.lines and turn.lines[-1] is ln:
            return
        turn.lines.append(Line(page=ln.page, line_no=ln.line_no, text=text, kind=ln.kind, synthetic=ln.synthetic, top=ln.top))

    # header lines become a caption turn so that every body line is citable
    if header.header_end_index > 0:
        cap = Turn(key="t_header", speaker=None, unit_type="caption", phase="preliminary")
        cap.lines = body[: header.header_end_index]
        turns.append(cap)

    current: Turn | None = None
    for ln in body[header.header_end_index:]:
        t = _pv(ln.text)
        raw = clean_line_text(ln.text)
        if not t:
            continue

        # witness introduction
        wm = WITNESS_INTRO_RE.match(t)
        if wm:
            name = _pv(wm.group("name")).strip(" ,")
            state["witness"] = f"{wm.group('role')} {name}".strip()
            if state["witness"] not in witnesses:
                witnesses.append(state["witness"])
            ph = INTRO_PHASE_RE.search(t)
            if ph:
                state["phase"] = PHASE_WORDS[ph.group("phase")]
            elif state["phase"] in {"preliminary", "argument"}:
                state["phase"] = "direct"
            am_ = INTRO_ASKER_RE.search(t)
            state["asker"] = directory.classify(am_.group("asker").strip(), state["witness"]) if am_ else None
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["witness_intro"])
            continue

        # examination heading
        pm = PHASE_HEADING_RE.match(t)
        if pm:
            state["phase"] = PHASE_WORDS[pm.group("phase")]
            if pm.group("asker"):
                state["asker"] = directory.classify(pm.group("asker").strip(), state["witness"])
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["phase_heading"])
            continue

        if COURT_DECISION_RE.match(t):
            current = new_turn(Speaker(label="בית המשפט", role="court", side="court", entity_key="court"), "decision",
                               Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top))
            state["speaker"] = current.speaker
            continue

        in_exam = state["phase"] in {"direct", "cross", "redirect", "recross"} and state["witness"]

        qm = Q_RE.match(t)
        am = A_RE.match(t)
        if qm or am:
            if not in_exam:
                # outside examination ש./ת. carry no reliable meaning
                if current is None:
                    current = new_turn(None, "other", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["qa_marker_outside_exam"])
                else:
                    add_text(current, ln, raw)
                    if "qa_marker_outside_exam" not in current.flags:
                        current.flags.append("qa_marker_outside_exam")
                continue
            if qm:
                q_text, a_text = _split_inline_answer(raw)
                asker = state["asker"] or Speaker(label="השואל", role="counsel", side=None)
                flags = [] if state["asker"] else ["asker_unknown"]
                current = new_turn(asker, "question", Line(ln.page, ln.line_no, q_text, ln.kind, ln.synthetic, ln.top), flags)
                if a_text:
                    wit = directory.classify(state["witness"], state["witness"])
                    current = new_turn(wit, "answer", Line(ln.page, ln.line_no, a_text, ln.kind, ln.synthetic, ln.top), ["inline_answer"])
            else:
                wit = directory.classify(state["witness"], state["witness"])
                current = new_turn(wit, "answer", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top))
            continue

        sm = SPEAKER_RE.match(t)
        if sm and len(sm.group("label")) <= 60:
            label_raw = _raw_label(raw)
            spk = directory.classify(label_raw, state["witness"])
            # a witness speaking under their own name inside examination is an answer
            unit_type = "speech_turn"
            if in_exam and spk.role == "witness":
                unit_type = "answer"
            current = new_turn(spk, unit_type, Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top))
            state["speaker"] = spk
            # arguments/opening statements by counsel outside examination
            if not in_exam and spk.role in {"prosecution", "defense", "counsel"} and state["phase"] == "preliminary":
                pass
            continue

        im = INTERRUPTION_RE.match(t)
        if im and current is not None and current.unit_type in {"question", "answer"}:
            # stage directions such as "(העד מעיין במסמך)" stay inside the turn
            add_text(current, ln, raw)
            continue

        if current is None:
            current = new_turn(None, "other", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["no_speaker"])
            warnings.append(f"text before first speaker at p{ln.page} l{ln.line_no}")
        else:
            add_text(current, ln, raw)

    _mark_court_questions(turns)
    units = _turns_to_units(turns, source_version_id)
    return ParsedProtocol(header=header, turns=turns, units=units, witnesses=witnesses, warnings=warnings)


def _mark_court_questions(turns: list[Turn]) -> None:
    """A judge's question during examination that is directly followed by the
    witness's answer is a court question (spec phase ``court_questions``)."""
    for a, b in zip(turns, turns[1:]):
        if (
            a.unit_type == "speech_turn"
            and a.speaker is not None
            and a.speaker.role == "judge"
            and b.unit_type == "answer"
            and "?" in "".join(ln.text for ln in a.lines)
        ):
            a.unit_type = "question"
            a.phase = "court_questions"
            b.phase = "court_questions"
            a.flags.append("court_question")


def _raw_label(raw: str) -> str:
    idx = raw.find(":")
    return raw[:idx].strip() if idx > 0 else raw


def _split_inline_answer(raw: str) -> tuple[str, str | None]:
    parts = INLINE_A_RE.split(raw, maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return raw, None


def _strip_marker(text: str, unit_type: str) -> str:
    if unit_type == "question":
        return re.sub(r"^ש\s*[.:\-–]\s*", "", text)
    if unit_type == "answer":
        return re.sub(r"^ת\s*[.:\-–]\s*", "", text)
    return text


def _turns_to_units(turns: list[Turn], source_version_id: str) -> list[UnitRecord]:
    units: list[UnitRecord] = []
    ordinal = 0
    for turn in turns:
        for part, (page, lines) in enumerate(turn.text_by_page()):
            text = "\n".join(ln.text for ln in lines).strip()
            if part == 0:
                text = _strip_marker(text, turn.unit_type)
            if not text:
                continue
            line_start = min(ln.line_no for ln in lines)
            line_end = max(ln.line_no for ln in lines)
            label = turn.speaker.label if turn.speaker else None
            uid = ids.source_unit_id(source_version_id, page, line_start, line_end, ordinal, label)
            units.append(
                UnitRecord(
                    id=uid,
                    ordinal=ordinal,
                    page=page,
                    line_start=max(1, line_start),
                    line_end=max(1, line_end),
                    speaker_label=label,
                    speaker_role=turn.speaker.role if turn.speaker else None,
                    speaker_side=turn.speaker.side if turn.speaker else None,
                    unit_type=turn.unit_type,
                    examination_phase=turn.phase,
                    raw_text=text,
                    turn_key=ids.stable_id("tk", [source_version_id, turn.key]),
                    turn_part=part,
                    witness_label=turn.witness,
                    synthetic_lines=any(ln.synthetic for ln in lines),
                    flags=list(turn.flags),
                )
            )
            ordinal += 1
    return units
