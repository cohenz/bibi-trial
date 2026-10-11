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

PARSER_VERSION = "protocol-parser-1.3"

# ---------------------------------------------------------------------------
# pinned text view used for structure detection only
# ---------------------------------------------------------------------------
ANCHOR_RE = re.compile(r"[<>]#\d+#[<>]")  # "<#3#>" anchors, also as reversed by visual-order repair
_BIDI = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"), None)


def _pv(text: str) -> str:
    s = unicodedata.normalize("NFC", text).translate(_BIDI)
    s = s.replace("״", '"').replace("”", '"').replace("“", '"').replace("׳", "'").replace("’", "'").replace("`", "'")
    s = ANCHOR_RE.sub(" ", s)  # Net-HaMishpat page anchors
    return re.sub(r"\s+", " ", s).strip()


def clean_line_text(text: str) -> str:
    """Raw text for storage: only anchors and bidi controls removed."""
    s = unicodedata.normalize("NFC", text).translate(_BIDI)
    s = ANCHOR_RE.sub(" ", s)
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------
HONORIFICS = r"(?:כב'\s*)?(?:השופטת|השופט|אב\"ד)"
COUNSEL = r"(?:עו\"ד|עוה\"ד|ב\"כ)"
SPEAKER_PREFIXES = (
    r"עו\"ד|עוה\"ד|ב\"כ|כב'|כבוד|השופטת|השופט|אב\"ד|העד|העדה|הנאשם|הנאשמת|נאשם|נאשמת|מר|גב'|ד\"ר|פרופ'|רו\"ח"
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
DATE_WORDS_RE = re.compile(r"\b(\d{1,2})\s+[בל]?-?(" + "|".join(HEB_MONTHS) + r")\s+(\d{4})\b")
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
WITNESS_CODE = r"(?:ע\"ה|ע\"ת|עד(?:ת)?\s+(?:ה)?(?:הגנה|תביעה))\s*(?:מס['\"]?\s*)?(?P<num>\d+)"
# "ע"ה 1 – נאשם 1 – לאחר שהוזהר…", "עד הגנה 4 - ח"כ משה סעדה , לאחר שהוזהר…", "ע"ה 5 - מר דובי שרצר, מוזהר כדין…"
# 2021–2023: "ע"ת 65 מר ינון מגל לאחר שהוזהר כדין…" (no dash), "ע"ת 8 - מר ניר חפץ משיב לשאלות עו"ד …" (no warning clause)
WITNESS_CODE_INTRO_RE = re.compile(
    rf"^(?P<code>{WITNESS_CODE})\s*[-–]?\s*(?P<name>.+?)\s*(?:[-–,]\s*)?"
    r"(?:לאחר\s+שהוזהר(?:ה)?|מוזהר(?:ת)?|לאחר\s+שהצהיר(?:ה)?|(?=משיב(?:ה)?\s+לשאלות))"
)
# hearing summary on the cover page: "העיד: ע"ה 1 – נאשם 1 – המשך חקירה נגדית לעו"ד …"
SUMMARY_WITNESS_RE = re.compile(r"^העיד(?:ו)?\s*:\s*(?P<rest>.+)$")
SUMMARY_ITEM_RE = re.compile(rf"(?P<code>{WITNESS_CODE})\s*[-–]?\s*(?P<body>.*?)(?=(?:\.\s*)?(?:ע\"ה|ע\"ת)\s*\d|$)")
# narrative cover note: "נמשכה חקירתו הנגדית של ע"ת 1 אילן ישועה, על ידי עו"ד ז'ק חן."
NARRATIVE_SUMMARY_RE = re.compile(
    rf"^(?:נמשכה|החלה|התחילה|הסתיימה|נשמעה|המשך)\s+חקירת(?:ו|ה)?\s+ה?(?P<phase>ראשית|נגדית|חוזרת)\s+של\s+"
    rf"(?:(?:העד|העדה)\s+)?(?:(?P<code>{WITNESS_CODE})\s*[-–]?\s*)?(?P<name>[^,.]+?)\s*"
    r"(?:,?\s*(?:על\s+ידי|ע\"י|לשאלות)\s+(?P<asker>[^,.]+?))?\s*\.?\s*$"
)
# furniture of the record itself, not anybody's speech
PROCEDURAL_NOTE_RE = re.compile(  # anywhere in the record
    r"^(?:תמליל\s+(?:ה)?פרוטוקול(?:\s+מוקלט)?\s*$|-\s*הדיון\s+(?:הסתיים|ננעל|נסתיים)\s*-|הוקלד\s+על\s+ידי\s)"
)
COVER_NOTE_RE = re.compile(  # cover page only: elsewhere these words can open a sentence of speech
    r"^(?:פרוטוקול\s+הדיון\s+הוקלט|הדיון\s+(?:התקיים|מתקיים)\s+ב|הוגשו\s+מוצגים|מוצגי\s)"
)
DEFENDANT_REF_RE = re.compile(r"^(?:ה)?נאשם\s*(?P<n>\d)$")
WITNESS_INTRO_RE = re.compile(
    r"^(?P<role>העד|העדה|עד התביעה|עדת התביעה|עד ההגנה|עדת ההגנה)\s*[,:]?\s*(?P<name>[^,]{2,60}?)\s*,?\s*"
    r"(?:לאחר\s+שהוזהר(?:ה)?|מוזהר(?:ת)?|לאחר\s+שהצהיר(?:ה)?)"
)
INTRO_PHASE_RE = re.compile(r"(?:ב)?חקירה\s+(?P<phase>ראשית|נגדית|חוזרת)")
INTRO_ASKER_RE = re.compile(r"(?:לשאלות|ע\"י|על ידי|של|ל(?=עו\"ד|ב\"כ))\s*(?P<asker>" + COUNSEL + r"\s*[^\s,:.]+(?:\s+(?!בחקירה|חקירה)[^\s,:.]+)?)")
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
    court_case_number_source: str | None = None  # "document" when read from the protocol itself, "hint" otherwise
    hearing_date: str | None = None
    court_name: str | None = None
    judges: list[str] = field(default_factory=list)
    attendees: list[tuple[str, str]] = field(default_factory=list)  # (label, side)
    header_end_index: int = 0
    defendants: dict[int, str] = field(default_factory=dict)  # number → name from the caption
    summary_witnesses: list[dict] = field(default_factory=list)  # from "העיד:" on the cover page


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
        if re.match(r"^(?:העד|העדה|עד התביעה|עדת התביעה|עד ההגנה|עדת ההגנה)(?=[\s,]|$)|^(?:ע\"ה|ע\"ת)\s*\d", lab):
            return Speaker(label=label, role="witness", side="witness", entity_key=_speaker_key(witness or label))
        if re.match(r"^(?:כב'|כבוד|השופט|השופטת|אב\"ד)", lab):
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

def _parse_defendants(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for m in re.finditer(r"(?<![\d/.-])(\d)\s*\.\s*([^\d,;]+?)(?=\s*,|\s+\d\s*\.|$)", text):
        name = m.group(2).strip(" .")
        if name and int(m.group(1)) not in out:
            out[int(m.group(1))] = name
    return out


def supplement_header(h: ProtocolHeader, furniture: list[Line]) -> None:
    """Running page headers ("לפני כבוד השופטים …", "ת"פ … 15 בספטמבר 2025") are tagged as
    furniture by the extractor; the facts in them still belong to the header."""
    for ln in furniture:
        t = _pv(ln.text)
        if h.hearing_date is None:
            h.hearing_date = parse_date(t)
        if h.court_case_number is None:
            m = CASE_NO_RE.search(t)
            if m:
                h.court_case_number = m.group(1)
        if h.court_name is None and t.startswith("בית המשפט"):
            h.court_name = t
        m = re.search(r"(?:לפני\s+)?(?:כבוד\s+|כב'\s+)?השופטים\s*:?\s*(?P<names>.+)$", t)
        if m and not h.judges:
            for name in re.split(r"\s*,\s*|\s+ו(?=[א-ת]{2,}\s)", m.group("names")):
                name = re.sub(r"\s*-\s*(?:אב\"ד|סגנית הנשיא|סגן הנשיא)$", "", name.strip(" ."))
                if name:
                    h.judges.append(name)


ATTENDANCE_TOKEN_RE = re.compile(
    r"(?P<pros>(?:ב\"כ\s+)?(?:המאשימה|התביעה|הפרקליטות))"
    r"|(?P<def>(?:ב\"כ\s+)?ה?נאש(?:ם|מים|מת|מות)(?![א-ת])\s*(?P<nums>\d(?:\s*(?:,|ו-?|-)\s*\d)*)?)"
    r"|(?P<cns>ו?(?:עו\"ד|עוה\"ד)\s*(?P<name>[^,;:()]+?))"
    r"(?=\s*[,;]|\s+ו?(?:עו\"ד|עוה\"ד)|\s+(?:וב\"כ|ב\"כ|מטעם|נאשם|הנאשם)|\s*[()]|$)"
)


def parse_attendance(text: str) -> list[tuple[str, str]]:
    """Counsel names with the side they appear under, in reading order.

    "ב"כ המאשימה, עו"ד א, עו"ד ב ועו"ד ג  נאשם 1 וב"כ, עו"ד ד  ב"כ נאשמים 2 ו-3 עו"ד ה" →
    א,ב,ג: prosecution; ד: defense_1; ה: defense_2."""
    out: list[tuple[str, str]] = []
    side: str | None = None
    for m in ATTENDANCE_TOKEN_RE.finditer(text):
        if m.group("pros"):
            side = "prosecution"
        elif m.group("def") is not None and m.group("def").strip():
            nums = re.findall(r"\d", m.group("nums") or "")
            side = f"defense_{nums[0]}" if nums else "defense"
        elif m.group("cns") and side:
            name = re.sub(r"\s+", " ", m.group("name")).strip(" -–.")
            if name:
                out.append((f'עו"ד {name}', side))
    return out


def parse_header(lines: list[Line], max_scan: int = 80) -> ProtocolHeader:
    h = ProtocolHeader()
    defendants_text: list[str] = []
    in_defendants = False
    attendance_mode = False
    attendance_text = ""
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
        if t.startswith("הנאשמים") or t.startswith("הנאשם "):
            in_defendants = True
            t_def = re.sub(r"^הנאשמ(?:ים|)\s*", "", t)
            defendants_text.append(t_def)
            continue
        if in_defendants:
            if ATTENDANCE_RE.match(t) or t == "נגד" or PROTOCOL_HEADING_RE.match(t):
                in_defendants = False
                h.defendants = _parse_defendants(" ".join(defendants_text))
            else:
                defendants_text.append(t)
                continue
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
            h.attendees = parse_attendance(attendance_text)
            return h
        if attendance_mode:
            # a name wrapped after "עו"ד" continues on the next line; otherwise a line break separates entries
            continuation = (re.search(rf"{COUNSEL}\s*$", attendance_text)
                            or (len(t.split()) <= 2 and not re.search(rf"{COUNSEL}|מטעם|נאשמ|נאשם|המאשימה", t)))
            sep = " " if continuation else " , "
            attendance_text = (attendance_text + sep + t) if attendance_text else t
    h.attendees = parse_attendance(attendance_text)
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
    body = [ln for ln in lines if ln.kind == "body" and clean_line_text(ln.text)]
    header = parse_header(body)
    first_page = min((ln.page for ln in lines), default=1)
    supplement_header(header, [ln for ln in lines if ln.kind == "header" and ln.page == first_page])
    if not header.court_case_number:
        for ln in lines[:200]:
            m = CASE_NO_RE.search(_pv(ln.text))
            if m:
                header.court_case_number = m.group(1)
                break
    if header.court_case_number:
        header.court_case_number_source = "document"
    elif case_number_hint:
        header.court_case_number = case_number_hint
        header.court_case_number_source = "hint"
    directory = SpeakerDirectory(header)
    warnings: list[str] = []

    turns: list[Turn] = []
    witnesses: list[str] = []
    state: dict = {"phase": "preliminary", "asker": None, "witness": None, "speaker": None, "from_summary": False}

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

    def witness_name(code: str | None, name: str) -> str:
        """Canonical witness name: titles dropped so the cover page ("פקד ארנון אליעז") and the
        introduction ("מר ארנון אליעז") resolve to one person."""
        name = _pv(name).strip(" ,.-–")
        name = re.sub(r"^(?:(?:מר|גב'|גברת|ד\"ר|פרופ'|ח\"כ|השר|השרה|פקד|רפ\"ק|סנ\"צ|נצ\"מ|תנ\"צ|ניצב|רס\"ר|עו\"ד|רו\"ח)\s+)+", "", name)
        dm = DEFENDANT_REF_RE.match(name)
        if dm and int(dm.group("n")) in header.defendants:
            return f"נאשם {dm.group('n')} — {header.defendants[int(dm.group('n'))]}"
        return name

    def adopt_summary_witness() -> bool:
        """Transcripts often start mid-examination with no introduction line; the cover
        page ("העיד: ע"ה 1 – נאשם 1 – המשך חקירה נגדית לעו"ד …") says who and how."""
        if not header.summary_witnesses:
            return False
        sw = header.summary_witnesses[0]
        state["witness"] = sw["witness"]
        if sw["witness"] not in witnesses:
            witnesses.append(sw["witness"])
        state["phase"] = sw.get("phase") or "direct"
        state["asker"] = directory.classify(sw["asker"], sw["witness"]) if sw.get("asker") else None
        state["from_summary"] = True
        return True

    current: Turn | None = None
    seq = body[header.header_end_index:]
    for idx, ln in enumerate(seq):
        t = _pv(ln.text)
        raw = clean_line_text(ln.text)
        if not t:
            continue

        if PROCEDURAL_NOTE_RE.match(t) or (ln.page == first_page and COVER_NOTE_RE.match(t)):
            # a procedural note closes the running turn; "הוגשו מוצגים: …" may wrap onto following lines
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["procedural_note"])
            continue

        nsm = NARRATIVE_SUMMARY_RE.match(t) if ln.page == first_page else None
        if nsm:
            name = witness_name(nsm.group("code"), nsm.group("name"))
            if name and all(w["witness"] != name for w in header.summary_witnesses):
                header.summary_witnesses.append({"code": _pv(nsm.group("code") or ""), "witness": name,
                                                 "phase": PHASE_WORDS[nsm.group("phase")],
                                                 "asker": nsm.group("asker").strip() if nsm.group("asker") else None,
                                                 "ended": nsm.group(0).startswith("הסתיימה")})
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["hearing_summary"])
            continue

        # cover-page summary of who testified
        smm = SUMMARY_WITNESS_RE.match(t)
        if smm:
            for it in SUMMARY_ITEM_RE.finditer(smm.group("rest")):
                parts = [x.strip() for x in re.split(r"\s+[-–]\s+", it.group("body").strip(" ."))]
                name = witness_name(it.group("code"), parts[0] if parts else "")
                rest = " ".join(parts[1:])
                ph = INTRO_PHASE_RE.search(rest)
                am_ = INTRO_ASKER_RE.search(rest)
                header.summary_witnesses.append({
                    "code": _pv(it.group("code")), "witness": name,
                    "phase": PHASE_WORDS[ph.group("phase")] if ph else None,
                    "asker": am_.group("asker").strip() if am_ else None, "ended": "הסתיימה" in rest})
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["hearing_summary"])
            continue

        # witness introduction with a witness code ("ע"ה 5 - מר דובי שרצר, מוזהר כדין…")
        cm = WITNESS_CODE_INTRO_RE.match(t)
        if cm:
            state["witness"] = witness_name(cm.group("code"), cm.group("name"))
            state["from_summary"] = False
            if state["witness"] not in witnesses:
                witnesses.append(state["witness"])
            look = t + " " + (_pv(seq[idx + 1].text) if idx + 1 < len(seq) else "")  # phase may wrap
            ph = INTRO_PHASE_RE.search(look)
            state["phase"] = PHASE_WORDS[ph.group("phase")] if ph else "direct"
            am_ = INTRO_ASKER_RE.search(look)
            state["asker"] = directory.classify(am_.group("asker").strip(), state["witness"]) if am_ else None
            current = new_turn(None, "caption", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["witness_intro"])
            continue
        if current is not None and "witness_intro" in current.flags and len(current.lines) == 1 \
                and re.match(r"^(?:ב)?(?:המשך\s+)?חקירה\s+(?:ראשית|נגדית|חוזרת)\s*:?$", t):
            add_text(current, ln, raw)  # wrapped tail of the introduction line
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
        if am and not in_exam and not state["witness"] and header.summary_witnesses:
            # the witness answering the bench before the examination starts ("ת. פקד, כן")
            sw = header.summary_witnesses[0]["witness"]
            wit = directory.classify(sw, sw)
            current = new_turn(wit, "answer", Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), ["witness_from_summary"])
            current.witness = sw
            continue
        if qm and not in_exam and adopt_summary_witness():
            in_exam = True
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
            if in_exam and spk.role in {"witness", "defendant"} and state["witness"] \
                    and spk.entity_key == directory.classify(state["witness"], state["witness"]).entity_key:
                unit_type = "answer"
            flags = []
            if in_exam and state["asker"] is not None and spk.role == state["asker"].role \
                    and _surname(spk.label) == _surname(state["asker"].label):
                flags.append("examiner_label")  # the examining counsel speaking under a name label
            current = new_turn(spk, unit_type, Line(ln.page, ln.line_no, raw, ln.kind, ln.synthetic, ln.top), flags)
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
    _demote_non_questions(turns)
    units = _turns_to_units(turns, source_version_id)
    return ParsedProtocol(header=header, turns=turns, units=units, witnesses=witnesses, warnings=warnings)


# A "ש." line is not always a question: counsel also acknowledges ("טוב.", "אוקיי."), interrupts
# ("רגע, מר נתניהו."), complains ("זו לא השאלה שלי") or answers the witness ("אני לא יודעת.").
# The next "ת." then continues the witness's earlier answer and must not be paired with it.
NON_QUESTION_RE = re.compile(
    r"^(?:(?:אז\s+)?(?:טוב|אוקיי|אוקי|או\s*קיי|בסדר(?:\s+גמור)?|יפה|תודה|נו|הבנתי|אני\s+הבנתי|רגע|רק\s+רגע|רגע\s+אחד)"
    r"[\s.,!-]*(?:(?:מר|גב'|ח\"כ)\s+\S+|אדוני|גברתי)?[\s.,!-]*$"
    r"|(?:(?:מר|גב'|ח\"כ)\s+\S+|אדוני|גברתי)[\s.,!-]*$"
    r"|(?:אדוני,?\s+)?(?:זו|זה|זאת)\s+לא\s+השאלה|אני\s+חוזר(?:ת)?\s+על\s+(?:ה)?שאלת?י|אני\s+אחזור\s+על\s+השאלה"
    r"|(?:אבל\s+)?(?:אתה|אדוני)\s+לא\s+מבין\s+מה\s+אני\s+אומר"
    r"|אני\s+לא\s+יודע(?:ת)?[\s.!]*$"
    r"|(?:אז\s+)?רגע\b"
    r"|(?:כן,?\s*)?(?:תיכף|מיד|עוד\s+מעט)\s+(?:אנחנו\s+)?(?:נראה|נגיע|נעבור))"
)
# the witness signalling that he is still finishing a previous answer
CONTINUATION_ANSWER_RE = re.compile(
    r"^(?:(?:רגע|רק\s+רגע),?\s*)?(?:תן\s+לי\s+(?:להשלים|לסיים)|תני\s+לי\s+(?:להשלים|לסיים)|(?:רק\s+)?אני\s+לא\s+סיימתי"
    r"|(?:עכשיו,?\s*)?זה\s+אחד|זו\s+תשובה\s+אחת|אני\s+רוצה\s+להשלים)"
)
PROMPT_ANSWER_RE = re.compile(r"^(?:נו,?\s*)?(?:אז|נו|כן|ו)\s*\?$")


def _turn_text(turn: Turn) -> str:
    text = "\n".join(ln.text for ln in turn.lines).strip()
    text = re.sub(r"^[שת]\s*[.:\-–]\s*", "", text)
    if turn.speaker and text.startswith(turn.speaker.label):
        text = text[len(turn.speaker.label):].lstrip(" :")
    return _pv(text)


def _demote_non_questions(turns: list[Turn]) -> None:
    """Questions without a question mark that are acknowledgements, interruptions or
    meta-remarks, or that the witness answers by finishing an earlier answer, are
    counsel's speech, not questions (measured on real protocols: these were the bulk
    of wrong Q/A pairs)."""
    for i, a in enumerate(turns):
        if a.unit_type != "question" or "court_question" in a.flags:
            continue
        qt = _turn_text(a)
        if "?" in qt:
            continue
        nxt = next((t for t in turns[i + 1:] if t.unit_type in {"answer", "question"}), None)
        at = _turn_text(nxt) if nxt is not None and nxt.unit_type == "answer" else ""
        if NON_QUESTION_RE.match(qt) or (at and (CONTINUATION_ANSWER_RE.match(at) or PROMPT_ANSWER_RE.match(at))):
            a.unit_type = "speech_turn"
            a.flags.append("non_question")


def _mark_court_questions(turns: list[Turn]) -> None:
    """A judge's question during examination that is directly followed by the
    witness's answer is a court question (spec phase ``court_questions``).
    The examining counsel speaking under a name label (instead of "ש.") and
    answered by the witness is an ordinary question of that examination."""
    for a, b in zip(turns, turns[1:]):
        if a.unit_type == "speech_turn" and "examiner_label" in a.flags and b.unit_type == "answer" \
                and "?" in "".join(ln.text for ln in a.lines):
            a.unit_type = "question"
            a.flags.append("labelled_question")
            continue
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
            a.witness = a.witness or b.witness  # a question to the witness before the examination began
            a.flags.append("court_question")


def _raw_label(raw: str) -> str:
    idx = raw.find(":")
    label = raw[:idx].strip() if idx > 0 else raw
    # transcription slip "עו"ד יונתן עו"ד יונתן תדמור" → the last full label
    hits = [m.start() for m in re.finditer(r'עו["״]ד|עוה["״]ד', label)]
    if len(hits) > 1:
        label = label[hits[-1]:].strip()
    return label


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
                text = _strip_marker(text, "question" if "non_question" in turn.flags else turn.unit_type)
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
