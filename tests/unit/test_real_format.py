"""Regression tests for layouts found in the real protocols of ת"פ 67104-01-20
(hearings of 15/16/17/29 September 2025). Excerpts are short quotations from the
public record, typed in as lines so the tests need no PDF."""

import os
from pathlib import Path

import pytest
from ntk_common.pipeline import pdf as pdfmod
from ntk_common.pipeline import run_l0
from ntk_common.pipeline.pdf import Line, PageText, _fix_bracket_orientation, _split_margin_number
from ntk_common.pipeline.protocol import _raw_label, parse_attendance, parse_protocol
from ntk_common.pipeline.qa import pair_exchanges


def _chars(spec: list[tuple[float, str]], size: float = 12.0) -> list[dict]:
    out = []
    for x0, text in spec:
        x = x0
        for ch in text:
            out.append({"x0": x, "x1": x + size * 0.45, "text": ch, "size": size, "top": 100.0})
            x += size * 0.45
    return out


def test_margin_number_close_to_text_is_split():
    # real file: number 61.7–67.0pt, text from 82.5pt on a 595pt page — closer than a column gap
    row = _chars([(61.7, "17"), (82.5, " ותירוש אמרה")])
    number, rest = _split_margin_number(row, 595.32)
    assert number == 17 and "".join(c["text"] for c in rest).strip() == "ותירוש אמרה"


def test_number_inside_text_is_not_a_margin_number():
    # "ב - 15" at the left end of a justified line, then the margin number 4: two tokens, not "415"
    row = _chars([(61.7, "4"), (85.0, "15 - ב"), (120.0, " צהריים")])
    number, rest = _split_margin_number(row, 595.32)
    assert number == 4
    row2 = _chars([(85.0, "2025"), (130.0, " לספטמבר")])  # a year near the edge is text
    assert _split_margin_number(row2, 595.32)[0] is None


def test_mirrored_brackets_repaired_per_document():
    pages = [PageText(page=1, lines=[Line(1, 1, ")העד יוצא מהאולם("), Line(1, 2, ">#3#<"), Line(1, 3, "עו\"ד פירר )בהעדר הנאשמים(")])]
    assert _fix_bracket_orientation(pages)
    assert [ln.text for ln in pages[0].lines] == ["(העד יוצא מהאולם)", "<#3#>", 'עו"ד פירר (בהעדר הנאשמים)']
    ok = [PageText(page=1, lines=[Line(1, 1, "(הפסקה)"), Line(1, 2, "(העד חוזר לאולם)")])]
    assert not _fix_bracket_orientation(ok)


def test_attendance_sides_real_phrasing():
    text = ('ב"כ המאשימה, עו"ד יהונתן תדמור, עו"ד יהודית תירוש, עו"ד קרן צבירן, עו"ד גל פורה , '
            'נאשם 1 וב"כ, עו"ד עמית חדד, עו"ד נועה מילשטיין ועו"ד ישראל וולנרמן , '
            'ב"כ נאשמים 2 ו-3, עו"ד נועה פירר (בהעדר הנאשמים)')
    sides = dict(parse_attendance(text))
    assert sides['עו"ד יהונתן תדמור'] == "prosecution" and sides['עו"ד גל פורה'] == "prosecution"
    # defense counsel must never be filed under the prosecution
    assert sides['עו"ד עמית חדד'] == "defense_1" and sides['עו"ד ישראל וולנרמן'] == "defense_1"
    assert sides['עו"ד נועה פירר'] == "defense_2"


def test_duplicated_label_slip():
    assert _raw_label('עו"ד יונתן עו"ד יונתן תדמור: לפי ההחלטה.') == 'עו"ד יונתן תדמור'


def _lines(rows: list[tuple[int, int, str, str]]) -> list[Line]:
    return [Line(page=p, line_no=n, text=t, kind=k) for p, n, t, k in rows]


COVER = [
    (1, 1, "בית המשפט המחוזי בירושלים", "header"),
    (1, 1, "לפני כבוד השופטים רבקה פרידמן-פלדמן, משה בר-עם, עודד שחם", "header"),
    (1, 1, "ת\"פ 67104-01-20 מדינת ישראל נ' נתניהו ואח' 16 בספטמבר 2025", "header"),
    (1, 1, "המאשימה מדינת ישראל", "body"),
    (1, 1, "נגד", "body"),
    (1, 1, "הנאשמים 1.", "body"),
    (1, 1, "בנימין נתניהו", "body"),
    (1, 1, "2. שאול אלוביץ', ת\"ז 042089367", "body"),
    (1, 2, "נוכחים:", "body"),
    (1, 3, 'ב"כ המאשימה, עו"ד יהונתן תדמור, עו"ד יהודית תירוש', "body"),
    (1, 4, 'נאשם 1 וב"כ, עו"ד עמית חדד', "body"),
    (1, 5, "פרוטוקול", "body"),
    (1, 6, "פרוטוקול הדיון הוקלט.", "body"),
    (1, 7, 'העיד: ע"ה 1 – נאשם 1 – המשך חקירה נגדית לעו"ד יהונתן תדמור.', "body"),
    (1, 8, "החלטה", "body"),
    (1, 9, "הדיון הבא קבוע מחר, 17.9.2025, החל מהשעה 09:00.", "body"),
    (2, 1, "תמליל פרוטוקול מוקלט", "body"),
    (2, 3, 'כב\' השופטת ר\' פרידמן-פלדמן - אב"ד: בוקר טוב לכולם.', "body"),
    (2, 4, 'עו"ד עמית חדד: אז נגיש אותה עכשיו, ממש עכשיו.', "body"),
    (2, 5, "ת. אנחנו התחלנו, כבודכם, פעולה עצימה אתמול.", "body"),
    (2, 6, "ש. אדוני, שאלתי על הפטור. זה נכון, אדוני?", "body"),
    (2, 7, "ת. זה מה שאני זוכר.", "body"),
    (2, 8, 'עו"ד יהונתן תדמור: ומי ביקש את השינוי?', "body"),
    (2, 9, "ת. אני לא זוכר.", "body"),
    (2, 10, 'כבוד השופט עודד שחם: רק שאלה אחת, מתי זה היה?', "body"),
    (2, 11, "ת. ב-2016.", "body"),
]


@pytest.fixture(scope="module")
def cover():
    return parse_protocol(_lines(COVER), source_version_id="sv_" + "0" * 26)


def test_header_from_running_furniture(cover):
    h = cover.header
    assert h.hearing_date == "2025-09-16"  # "16 בספטמבר 2025" — month with the ב prefix
    assert h.judges == ["רבקה פרידמן-פלדמן", "משה בר-עם", "עודד שחם"]
    assert h.defendants[1] == "בנימין נתניהו" and h.defendants[2] == "שאול אלוביץ'"
    assert h.summary_witnesses[0]["witness"] == "נאשם 1 — בנימין נתניהו"
    assert h.summary_witnesses[0]["phase"] == "cross" and h.summary_witnesses[0]["asker"] == 'עו"ד יהונתן תדמור'


def test_transcript_without_intro_uses_cover_summary(cover):
    units = cover.units
    q = next(u for u in units if u.raw_text.startswith("אדוני, שאלתי"))
    assert q.unit_type == "question" and q.speaker_label == 'עו"ד יהונתן תדמור' and q.speaker_side == "prosecution"
    assert q.examination_phase == "cross" and q.witness_label == "נאשם 1 — בנימין נתניהו"
    a = next(u for u in units if u.raw_text == "זה מה שאני זוכר.")
    assert a.unit_type == "answer" and a.speaker_label == "נאשם 1 — בנימין נתניהו"
    hadad = next(u for u in units if u.raw_text.startswith('עו"ד עמית חדד'))
    assert hadad.speaker_side == "defense_1" and hadad.unit_type == "speech_turn"


def test_examiner_label_and_court_questions(cover):
    units = cover.units
    tq = next(u for u in units if u.raw_text.startswith('עו"ד יהונתן תדמור: ומי ביקש'))
    assert tq.unit_type == "question" and "labelled_question" in tq.flags
    jq = next(u for u in units if u.raw_text.startswith("כבוד השופט עודד שחם"))
    assert jq.speaker_role == "judge" and jq.unit_type == "question" and jq.examination_phase == "court_questions"
    exchanges, warnings = pair_exchanges(units)
    assert len(exchanges) == 3 and not warnings


def test_procedural_notes_do_not_join_decisions(cover):
    dec = next(u for u in cover.units if u.unit_type == "decision")
    assert "תמליל" not in dec.raw_text
    notes = [u for u in cover.units if "procedural_note" in u.flags]
    assert {u.raw_text for u in notes} == {"פרוטוקול הדיון הוקלט.", "תמליל פרוטוקול מוקלט"}


def test_code_intro_with_wrapped_phase():
    rows = COVER[:13] + [
        (2, 1, 'ע"ה 6 - מר ארנון אליעז לאחר שהוזהר כדין משיב לשאלות עו"ד עמית חדד', "body"),
        (2, 2, "בחקירה ראשית:", "body"),
        (2, 3, "ש. מר אליעז, ספר בקצרה על תפקידך.", "body"),
        (2, 4, "ת. אני התגייסתי כצוער במרץ 2016.", "body"),
    ]
    p = parse_protocol(_lines(rows), source_version_id="sv_" + "1" * 26)
    q = next(u for u in p.units if u.unit_type == "question")
    assert q.examination_phase == "direct" and q.speaker_side == "defense_1" and q.witness_label == "ארנון אליעז"


REAL_DIR = os.environ.get("NTK_REAL_PDF_DIR")


@pytest.mark.skipif(not REAL_DIR, reason="set NTK_REAL_PDF_DIR to the folder with the real protocols")
@pytest.mark.parametrize("name", ["0421", "0422", "0423", "0424"])
def test_real_protocols_structure(name):
    f = next(Path(REAL_DIR).glob(f"{name}_*.pdf"))
    r = run_l0(f.read_bytes(), document_id=f"doc_{name}", allow_ocr=False)
    assert all(p.printed_line_numbers for p in r.extracted.pages)
    body = [u for u in r.parsed.units if u.unit_type != "caption"]
    assert sum(u.synthetic_lines for u in body) <= 5
    assert r.parsed.header.hearing_date and len(r.parsed.header.judges) == 3
    assert all(u.speaker_label for u in body), "every non-caption unit has a speaker"
    assert len(r.exchanges) > 200
    sides = {u.speaker_label: u.speaker_side for u in r.parsed.units if u.speaker_label and "חדד" in u.speaker_label}
    assert sides and all(s == "defense_1" for s in sides.values())
    assert pdfmod  # imported for the skip message
