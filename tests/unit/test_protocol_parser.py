"""Parser behaviour on the synthetic fixture (fictional names and case)."""

import pytest
from ntk_common import ids
from ntk_common.pipeline import run_l0
from ntk_common.pipeline.pdf import PdfValidationError, validate_pdf
from ntk_common.pipeline.qa import classify_answer


@pytest.fixture(scope="module")
def l0(fixture_pdf):
    return run_l0(fixture_pdf, document_id=ids.source_document_id("case-x", "fixture"), allow_ocr=False)


def test_header(l0):
    h = l0.parsed.header
    assert h.court_case_number == "99999-01-20"
    assert h.hearing_date == "2021-04-12"
    assert h.judges == ["שרה כהן", "יוסף לוי", "אבי מזרחי"]
    sides = dict(h.attendees)
    assert sides['עו"ד רחל אדלר'] == "prosecution" and sides['עו"ד משה גולן'] == "defense_1"


def test_printed_line_numbers_and_rtl_repair(l0):
    assert all(p.printed_line_numbers for p in l0.extracted.pages)
    assert all(p.visual_order_fixed for p in l0.extracted.pages)


def test_speakers_and_roles(l0):
    by_text = {u.raw_text[:20]: u for u in l0.parsed.units}
    q1 = next(u for u in l0.parsed.units if u.raw_text.startswith("אתה עבדת בחברה"))
    assert q1.unit_type == "question" and q1.speaker_label == 'עו"ד אדלר' and q1.speaker_side == "prosecution"
    a1 = next(u for u in l0.parsed.units if u.raw_text == "כן." and u.unit_type == "answer")
    # the witness shares a surname with a judge — must still be the witness
    assert a1.speaker_role == "witness" and a1.speaker_label.startswith("העד")
    assert by_text  # sanity


def test_phases(l0):
    cross = [u for u in l0.parsed.units if u.examination_phase == "cross" and u.unit_type == "question"]
    assert cross and all(u.speaker_side == "defense_1" for u in cross)
    cq = [u for u in l0.parsed.units if u.examination_phase == "court_questions"]
    assert {u.unit_type for u in cq} == {"question", "answer"}


def test_turn_split_at_page_boundary_keeps_turn_key(l0):
    by_turn: dict[str, list] = {}
    for u in l0.parsed.units:
        by_turn.setdefault(u.turn_key, []).append(u)
    for parts in by_turn.values():
        assert len({p.page for p in parts}) == len(parts)  # one unit per page per turn


def test_question_and_answer_never_merged(l0):
    for e in l0.exchanges:
        assert e.question.id != e.answer.id
        assert e.question.unit_type == "question" and e.answer.unit_type == "answer"


def test_exchange_relations(l0):
    def rel(prefix):
        return next(e.answer_relation for e in l0.exchanges if e.question.raw_text.startswith(prefix))

    assert rel("אתה עבדת בחברה") == "affirms"
    assert rel("נכון שבאותה תקופה") == "qualified_affirmation"
    assert rel("האם נכחת בפגישה") == "does_not_know"
    assert rel("נכון שבפגישה ההיא") == "denies"
    assert rel("ממש לא היה ברור") == "nonresponsive"
    assert rel("אתה מסכים שלא ראית") == "affirms"


def test_public_wording_only_for_clean_affirm_or_deny(l0):
    for e in l0.exchanges:
        if e.public_wording:
            assert e.answer_relation in {"affirms", "denies"} and not e.flags
        if e.answer_relation in {"qualified_affirmation", "ambiguous"}:
            assert e.public_wording is None


def test_interrupted_pair_is_flagged(l0):
    interrupted = [e for e in l0.exchanges if "interrupted" in e.flags]
    assert len(interrupted) == 1 and interrupted[0].public_wording is None


def test_ids_stable_across_runs(fixture_pdf, l0):
    again = run_l0(fixture_pdf, document_id=ids.source_document_id("case-x", "fixture"), allow_ocr=False)
    assert [u.id for u in again.parsed.units] == [u.id for u in l0.parsed.units]
    assert [c.id for c in again.chunks] == [c.id for c in l0.chunks]
    assert [e.id for e in again.exchanges] == [e.id for e in l0.exchanges]


def test_chunks_are_whole_units(l0):
    unit_ids = {u.id for u in l0.parsed.units}
    for c in l0.chunks:
        assert set(c.ordered_source_unit_ids) <= unit_ids and 1 <= c.token_count <= 2000


@pytest.mark.parametrize("q,a,expected", [
    ("נכון שהיית שם?", "כן", "affirms"),
    ("נכון שהיית שם?", "נכון, אבל רק לחצי שעה", "qualified_affirmation"),
    ("נכון שהיית שם?", "לא", "denies"),
    ("נכון שהיית שם?", "לא זוכר", "does_not_know"),
    ("נכון שהיית שם?", "אינני זוכר את זה", "does_not_know"),
    ("נכון שהיית שם?", "מה זאת אומרת?", "nonresponsive"),
    ("מה עשית אחר כך?", "הלכתי הביתה ואז התקשרתי למנהל", "ambiguous"),
    ("נכון שהיית שם?", "יכול להיות", "qualified_affirmation"),
])
def test_classify_answer(q, a, expected):
    assert classify_answer(q, a)[0] == expected


def test_validate_pdf_rejects_bad_input(fixture_pdf):
    with pytest.raises(PdfValidationError) as e1:
        validate_pdf(b"hello")
    assert e1.value.code == "not_a_pdf"
    with pytest.raises(PdfValidationError) as e2:
        validate_pdf(fixture_pdf, expected_sha256="0" * 64)
    assert e2.value.code == "checksum_mismatch"
    with pytest.raises(PdfValidationError) as e3:
        validate_pdf(fixture_pdf, declared_mime="text/html")
    assert e3.value.code == "unsupported_mime"
    with pytest.raises(PdfValidationError) as e4:
        validate_pdf(fixture_pdf, max_bytes=100)
    assert e4.value.code == "file_too_large"
