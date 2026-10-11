"""Object-store inbox: listing, classification, duplicates, foreign cases, ingestion of non-protocol documents and the
auto-publication policy (protocols, decisions, motions, responses and notices whose own pages carry the case
number)."""

from __future__ import annotations

import pytest
from ntk_common import inbox
from ntk_common.db.core import row, rows, scalar
from ntk_common.jobs import TASK_RUN_JOB, InlineQueue

pytest.importorskip("reportlab", reason="synthetic document PDFs are drawn with reportlab (dev dependency)")
from tests.doc_fixtures import DECISION, FOREIGN_DECISION, MOTION, blank_pdf, make_pdf  # noqa: E402

pytestmark = pytest.mark.db


def test_classify_by_rules_headings():
    c = inbox.classify_by_rules("\n".join(DECISION[0]), "", "x.pdf", case_number="67104-01-20")
    assert (c.source_type, c.case_found, c.document_date) == ("decision", True, "2025-10-12")
    assert c.confidence >= 0.9 and "tail:ניתנה היום" in c.signals
    c = inbox.classify_by_rules("\n".join(MOTION[0]), "\n".join(MOTION[1]), "x.pdf", case_number="67104-01-20")
    assert (c.source_type, c.title) == ("motion", "בקשה לדחיית מועד דיון")
    c = inbox.classify_by_rules("פרוטוקול\nנוכחים:\n15 בספטמבר 2025\nת\"פ 67104-01-20", "", "a.pdf", case_number="67104-01-20")
    assert (c.source_type, c.hearing_date, c.case_found) == ("protocol", "2025-09-15", True)
    c = inbox.classify_by_rules("\n".join(FOREIGN_DECISION[0]), "", "y.pdf", case_number="67104-01-20")
    assert c.case_found is False
    c = inbox.classify_by_rules("סתם טקסט", "", "z.pdf", case_number="67104-01-20")
    assert c.source_type == "other" and c.confidence < inbox.MODEL_THRESHOLD and c.case_found is None


@pytest.fixture(scope="module")
def inbox_run(services, pipeline):
    st = services.storage
    files = {
        "inbox/2025/החלטה-12-10.pdf": make_pdf(DECISION),
        "inbox/2025/בקשה.pdf": make_pdf(MOTION),
        "inbox/copies/same-decision.pdf": make_pdf(DECISION),
        "inbox/other-court.pdf": make_pdf(FOREIGN_DECISION),
        "inbox/scan.pdf": blank_pdf(),
        "inbox/notes.txt": b"just notes",
    }
    for k, v in files.items():
        st.put_bytes(k, v, mime_type="application/octet-stream")
    sid = inbox.start_scan(services.engine, trigger="test")
    res = inbox.list_new(services, prefix="inbox/", scan_id=sid)
    statuses = {iid: inbox.classify_item(services, iid) for iid in res["pending_ids"]}
    inbox.finish_scan(services.engine, sid, stats={"new": res["new"]})
    return res, statuses


def _item(services, key):
    with services.engine.connect() as conn:
        return row(conn, "SELECT * FROM ntk.inbox_items WHERE object_key = :k", {"k": key})


def test_scan_registers_and_classifies(services, inbox_run):
    res, statuses = inbox_run
    assert res["new"] == 6 and res["listed"] == 6
    dec = _item(services, "inbox/2025/החלטה-12-10.pdf")
    assert (dec["status"], dec["doc_kind"]) == ("classified", "decision")
    assert dec["classification"]["case_found"] is True and dec["source_key"].startswith("sources/sha256/")
    assert services.storage.head(dec["source_key"]) is not None  # copied to the immutable content key
    mot = _item(services, "inbox/2025/בקשה.pdf")
    assert (mot["status"], mot["doc_kind"]) == ("classified", "motion")
    dup = _item(services, "inbox/copies/same-decision.pdf")
    assert dup["status"] == "duplicate" and dup["duplicate_of"] == f"inbox:{dec['id']}"
    assert _item(services, "inbox/other-court.pdf")["status"] == "foreign_case"
    assert _item(services, "inbox/notes.txt")["status"] == "unsupported"
    scan = _item(services, "inbox/scan.pdf")
    assert scan["status"] == "classified" and scan["doc_kind"] == "other"  # no text: low confidence, left for review
    assert scan["classification"]["confidence"] < inbox.MODEL_THRESHOLD
    # a second scan finds nothing new and does not re-classify
    sid = inbox.start_scan(services.engine, trigger="test")
    again = inbox.list_new(services, prefix="inbox/", scan_id=sid)
    assert again["new"] == 0 and again["pending_ids"] == []


def test_process_ingests_documents_and_applies_publication_policy(services, pipeline, inbox_run):
    q = InlineQueue({TASK_RUN_JOB: lambda jid: pipeline.run_job(jid)})
    res = inbox.queue_items(services, q, task_name=TASK_RUN_JOB, kinds=["decision", "motion"])
    assert res == {"queued": 2, "jobs_created": 2}
    for key, kind, published in (("inbox/2025/החלטה-12-10.pdf", "decision", True), ("inbox/2025/בקשה.pdf", "motion", True)):
        it = _item(services, key)
        with services.engine.begin() as conn:
            job = row(conn, "SELECT status FROM ntk.ingestion_jobs WHERE id = :j", {"j": it["job_id"]})
            assert job["status"] == "succeeded"
            inbox.sync_job_status(conn, str(it["job_id"]), job["status"])
        it = _item(services, key)
        assert it["status"] == "ingested"
        with services.engine.connect() as conn:
            sv = row(conn, """SELECT sv.id, sv.publication_state, d.source_type::text AS st, sv.metadata
                              FROM ntk.source_versions sv JOIN ntk.source_documents d ON d.id = sv.document_id
                              WHERE sv.content_sha256 = :s""", {"s": it["content_sha256"]})
            units = rows(conn, "SELECT unit_type, speaker_label, hearing_id, page_no, line_start, raw_text "
                               "FROM ntk.source_units WHERE source_version_id = :sv ORDER BY unit_ordinal", {"sv": sv["id"]})
            chunks = scalar(conn, "SELECT count(*) FROM ntk.retrieval_chunks WHERE source_version_id = :sv", {"sv": sv["id"]})
        assert sv["st"] == kind and (sv["publication_state"] == "published") is published
        assert sv["metadata"]["original_filename"] == key
        assert units and chunks >= 1 and all(u["hearing_id"] is None for u in units)
        if kind == "decision":
            assert {u["unit_type"] for u in units} == {"decision"} and units[0]["speaker_label"] == "בית המשפט"
            assert any("הבקשה נדחית" in u["raw_text"] for u in units)
            assert len(units) >= 3  # paragraphs, not one blob
        else:
            assert {u["unit_type"] for u in units} == {"other"} and {u["page_no"] for u in units} == {1, 2}
    # queuing again creates nothing
    assert inbox.queue_items(services, q, task_name=TASK_RUN_JOB, kinds=["decision"]) == {"queued": 0, "jobs_created": 0}
    with services.engine.connect() as conn:
        s = inbox.summary(conn)
    assert s["by_status"]["ingested"] == 2 and s["by_kind"]["decision"] >= 2


def test_archive_file_names_give_titles_and_dates():
    fm = inbox.filename_meta("inbox/2021/0903 — 2021-05-19 — פרוטוקול — הדיון מיום 19_05_2021.pdf")
    assert fm == {"number": "0903", "date": "2021-05-19", "type_label": "פרוטוקול", "description": "הדיון מיום 19/05/2021"}
    assert inbox.filename_meta("inbox/x/0043 — 2026-05-25 — החלטה — שניתנה ע_י רבקה.pdf")["description"] == 'שניתנה ע"י רבקה'
    assert "description" not in inbox.filename_meta("inbox/0532 — 2026-10-04 — מסמך — מסמך.pdf")
    assert inbox.filename_meta("inbox/random name.pdf") == {}
    it = {"doc_kind": "notice", "object_key": "inbox/0938 — 2021-08-29 — הודעה — המדינה תעבור על התכתובות.pdf"}
    assert inbox.document_date_for(it, {"document_date": "7071-06-09"}) == "2021-08-29"
    assert inbox._title(it, {"title": "הודעה לבית המשפט הנכבד"}) == "הודעה: המדינה תעבור על התכתובות"
    it = {"doc_kind": "motion", "object_key": "inbox/scan.pdf"}
    assert inbox.document_date_for(it, {"document_date": "2014-07-14"}) is None  # older than the case
    assert inbox._title(it, {"title": "בקשה לדחייה"}) == "בקשה לדחייה — scan.pdf"
    prot = {"doc_kind": "protocol", "object_key": "inbox/0243 — 2023-09-21 — מסמך — מסמך.pdf"}
    assert inbox.document_date_for(prot, {"hearing_date": "2023-09-06"}) == "2023-09-06"
    assert inbox._title(prot, {"hearing_date": "2023-09-06"}) == "פרוטוקול דיון — 2023-09-06"
