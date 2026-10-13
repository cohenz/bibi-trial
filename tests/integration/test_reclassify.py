"""One-page court decisions that mention a protocol are documents, not hearings (11.10.2026)."""

from __future__ import annotations

import pytest
from ntk_common import inbox, reclassify
from ntk_common.db.core import execute, row, scalar
from ntk_common.jobs import TASK_RUN_JOB, InlineQueue

pytest.importorskip("reportlab", reason="synthetic document PDFs are drawn with reportlab (dev dependency)")
from tests.conftest import make_job  # noqa: E402
from tests.doc_fixtures import make_pdf  # noqa: E402

pytestmark = pytest.mark.db

COURT_DECISION = [[
    "בית המשפט המחוזי בירושלים",
    "ת\"פ 67104-01-20 מדינת ישראל נ' פלוני ואח'",
    "לפני כב' השופטת, סגנית הנשיא",
    "",
    "העתק החלטת בית משפט מיום 26 ביולי 2026",
    "",
    "פרוטוקול הדיון מיום 3.11.2021 נבדק על ידי חברת ההקלטות ותומלל מחדש.",
    "המזכירות תודיע לבאי כוח הצדדים.",
    "",
    "ניתנה היום, 26 ביולי 2026, בהעדר הצדדים.",
]]


def test_classifier_needs_attendance_or_turns():
    c = inbox.classify_by_rules("\n".join(COURT_DECISION[0]), "", "0008_1.pdf", case_number="67104-01-20")
    assert c.source_type == "decision"
    proto = "פרוטוקול\nנוכחים:\nמטעם המאשימה: עו\"ד א'\n15 בספטמבר 2025\nת\"פ 67104-01-20"
    assert inbox.classify_by_rules(proto, "", "a.pdf", case_number="67104-01-20").source_type == "protocol"
    turns = "פרוטוקול דיון\nכב' השופטת: נתחיל.\nעו\"ד חדד: בוקר טוב.\n15 בספטמבר 2025"
    assert inbox.classify_by_rules(turns, "", "a.pdf", case_number="67104-01-20").source_type == "protocol"
    assert reclassify.is_hearing_record(["other"], "נוכחים: עו\"ד") and not reclassify.is_hearing_record(["other"], "החלטה")
    assert reclassify.guess_kind("הודעה לצדדים", "x.pdf") == "notice"
    assert reclassify.guess_kind("טקסט", "inbox/0051 — 2026-06-30 — החלטה — תיאור.pdf") == "decision"


def test_pipeline_does_not_make_a_hearing_out_of_a_decision(services, pipeline):
    services.storage.put_bytes("inbox/reclass/0008_1.pdf", make_pdf(COURT_DECISION), mime_type="application/pdf")
    sid = inbox.start_scan(services.engine, trigger="test")
    ids_ = inbox.list_new(services, prefix="inbox/reclass/", scan_id=sid)["pending_ids"]
    for iid in ids_:
        inbox.classify_item(services, iid)
    with services.engine.begin() as conn:  # as if an older classifier had said "protocol"
        execute(conn, "UPDATE ntk.inbox_items SET doc_kind = 'protocol', status = 'classified' WHERE id = ANY(CAST(:i AS uuid[]))",
                {"i": ids_})
    inbox.queue_items(services, InlineQueue({TASK_RUN_JOB: lambda j: pipeline.run_job(j)}), task_name=TASK_RUN_JOB,
                      item_ids=ids_)
    with services.engine.connect() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:i AS uuid)", {"i": ids_[0]})
        job = row(conn, "SELECT status, input FROM ntk.ingestion_jobs WHERE id = :j", {"j": it["job_id"]})
        sv = row(conn, """SELECT sv.id, d.source_type::text AS st, d.canonical_title, sv.metadata FROM ntk.source_versions sv
                          JOIN ntk.source_documents d ON d.id = sv.document_id WHERE sv.content_sha256 = :s""",
                 {"s": it["content_sha256"]})
        assert job["status"] == "succeeded" and job["input"]["document"]["source_type"] == "decision"
        assert sv["st"] == "decision" and sv["metadata"]["reclassified_from"] == "protocol"
        assert it["doc_kind"] == "decision"
        assert scalar(conn, "SELECT count(*) FROM ntk.hearings WHERE source_version_id = :sv", {"sv": sv["id"]}) == 0


def test_existing_false_hearing_is_demoted(services, pipeline, tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_bytes(make_pdf([[ln.replace("26 ביולי", "27 ביולי") for ln in COURT_DECISION[0]]]))
    job = pipeline.run_job(make_job(services, str(path), hearing_date="2026-07-27"))
    with services.engine.begin() as conn:
        hid = scalar(conn, "SELECT id FROM ntk.hearings WHERE source_version_id = :sv",
                     {"sv": job["source_version_id"] if "source_version_id" in job else
                      scalar(conn, "SELECT source_version_id FROM ntk.ingestion_jobs WHERE id = :j", {"j": job["id"]})})
        assert hid, "the old path made a hearing of it"
        found = [c for c in reclassify.candidates(conn) if c["id"] == hid]
        assert found and found[0]["kind"] == "decision"
        res = reclassify.demote(conn, hearing_id=hid, kind="decision", actor="test")
        assert res["demoted"]
        assert scalar(conn, "SELECT count(*) FROM ntk.hearings WHERE id = :h", {"h": hid}) == 0
        assert scalar(conn, "SELECT count(*) FROM ntk.source_units WHERE hearing_id = :h", {"h": hid}) == 0
        st = scalar(conn, "SELECT d.source_type::text FROM ntk.source_versions sv JOIN ntk.source_documents d "
                          "ON d.id = sv.document_id WHERE sv.id = :sv", {"sv": res["source_version_id"]})
        assert st == "decision"
        assert scalar(conn, """SELECT count(*) FROM ntk.generated_artifacts WHERE object_type = 'hearing' AND object_id = :h
                               AND review_state <> 'superseded'""", {"h": hid}) == 0
        assert not [c for c in reclassify.candidates(conn) if c["id"] == hid]


def test_operator_names_a_record_the_rule_misses(services, pipeline, tmp_path):
    """A motion that mentions "נוכחים" passes the rule; the operator names it (and its type) and it is demoted."""
    path = tmp_path / "motion.pdf"
    path.write_bytes(make_pdf([[ln.replace("26 ביולי", "28 ביולי") for ln in COURT_DECISION[0]]]))
    job = pipeline.run_job(make_job(services, str(path), hearing_date="2026-07-28"))
    with services.engine.begin() as conn:
        sv = scalar(conn, "SELECT source_version_id FROM ntk.ingestion_jobs WHERE id = :j", {"j": job["id"]})
        hid = scalar(conn, "SELECT id FROM ntk.hearings WHERE source_version_id = :sv", {"sv": sv})
        found = reclassify.named(conn, [hid], kind="motion")
        assert [c["id"] for c in found] == [hid] and found[0]["kind"] == "motion"
        res = reclassify.demote(conn, hearing_id=hid, kind=found[0]["kind"], actor="test")
        assert res["demoted"]
        assert scalar(conn, "SELECT d.source_type::text FROM ntk.source_versions sv JOIN ntk.source_documents d "
                            "ON d.id = sv.document_id WHERE sv.id = :sv", {"sv": sv}) == "motion"
        assert reclassify.named(conn, [hid]) == []
