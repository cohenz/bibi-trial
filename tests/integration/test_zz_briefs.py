"""(Runs last: earlier modules assume a database holding only their own fixtures.) Document briefs: title, summary, significance and hearing days for non-protocol documents (mock provider)."""

from __future__ import annotations

import pytest
from ntk_common import briefs, gates, inbox
from ntk_common.db import guides_public as gp
from ntk_common.db import public as pub
from ntk_common.db.core import row
from ntk_common.jobs import TASK_RUN_JOB, InlineQueue
from ntk_common.layers import UnitView

pytest.importorskip("reportlab", reason="synthetic document PDFs are drawn with reportlab (dev dependency)")
from tests.doc_fixtures import make_pdf  # noqa: E402

pytestmark = pytest.mark.db

COURT_NOTICE = [[
    "בית המשפט המחוזי בירושלים",
    "ת\"פ 67104-01-20 מדינת ישראל נ' פלוני ואח'",
    "לפני כבוד השופטים",
    "",
    "החלטה",
    "",
    "פרוטוקול הדיון מיום 20.4.2026 הוקלט. בדיון העידה עדת הגנה 15 אילנית פילבר והוגש מוצג נ/4537.",
    "",
    "הדיון הבא יתקיים ביום 26.4.2026 בשעה 09:30.",
    "",
    "ניתנה היום, 21 באפריל 2026, בהעדר הצדדים.",
]]


def _u(i, text, unit_type="other", role=None):
    return UnitView(id=f"su_{i:026x}", source_version_id="sv_" + "0" * 26, page=1, line_start=i, line_end=i,
                    speaker_label=None, speaker_role=role, unit_type=unit_type, text=text)


def test_court_wording_only_in_court_documents():
    court, party = _u(1, "בית המשפט החליט לדחות את הבקשה", "decision", "court"), _u(2, "ההגנה מבקשת לדחות")
    by_id = {court.id: court, party.id: party}
    a = [gates.Assertion("summary_sentences/1", "בית המשפט החליט לדחות את הבקשה", [court.id])]
    assert briefs._court_wording_gate(a, by_id, court_doc=True).passed
    assert not briefs._court_wording_gate(a, by_id, court_doc=False).passed
    b = [gates.Assertion("summary_sentences/1", "בית המשפט החליט לדחות את הבקשה", [party.id])]
    assert not briefs._court_wording_gate(b, by_id, court_doc=True).passed  # court wording must cite the court's text
    days = [{"hearing_date": "2026-04-20", "witnesses": [{"name": "אילנית פילבר", "side": "defense", "description": ""}],
             "next_hearing_date": None, "citation_ids": [party.id]}]
    assert not briefs._witness_gate(days, by_id).passed


def test_notice_brief_hearing_day_on_timeline_and_witness(services):
    import dataclasses

    from ntk_common.orchestrator import Pipeline

    pipeline = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, auto_publish="gates")))
    services.storage.put_bytes("inbox/briefs/0018 — 2026-04-21 — החלטה — שניתנה ע_י רבקה.pdf", make_pdf(COURT_NOTICE),
                               mime_type="application/pdf")
    sid = inbox.start_scan(services.engine, trigger="test")
    ids_ = inbox.list_new(services, prefix="inbox/briefs/", scan_id=sid)["pending_ids"]
    for iid in ids_:
        inbox.classify_item(services, iid)
    inbox.queue_items(services, InlineQueue({TASK_RUN_JOB: lambda j: pipeline.run_job(j)}), task_name=TASK_RUN_JOB,
                      item_ids=ids_)
    with services.engine.connect() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE id = CAST(:i AS uuid)", {"i": ids_[0]})
        sv = row(conn, "SELECT id, publication_state::text AS ps FROM ntk.source_versions WHERE content_sha256 = :s",
                 {"s": it["content_sha256"]})
        art = row(conn, """SELECT payload, review_state::text AS st FROM ntk.generated_artifacts
                           WHERE object_type = 'document' AND object_id = :sv ORDER BY created_at DESC LIMIT 1""", {"sv": sv["id"]})
        assert sv["ps"] == "published"
        p = art["payload"]
        assert p["significance"] == "procedural" and p["title"]["text"]
        assert p["hearing_days"] and p["hearing_days"][0]["hearing_date"] == "2026-04-20"
        assert p["hearing_days"][0]["witnesses"][0]["name"] == "אילנית פילבר"
        assert art["st"] == "published", art["st"]  # a clean brief is published with its source (ADR-0014)
        doc = pub.public_document(conn, sv["id"])
        assert doc["brief"]["title"] == p["title"]["text"] and doc["display_title"] == p["title"]["text"]
        assert doc["brief"]["summary_sentences"] and doc["significance"] == "procedural"
        assert all(d["significance"] == "procedural" for d in pub.public_documents(conn, source_type=None, limit=500, offset=0,
                                                                                  significance="procedural"))
        assert sv["id"] not in {d["source_version_id"] for d in pub.public_documents(conn, source_type=None, limit=500,
                                                                                     offset=0, significance="substantive")}
        tl = gp.timeline(conn)
        day = [e for e in tl["events"] if e["kind"] == "hearing_day" and e["date"] == "2026-04-20"]
        assert day and "אילנית פילבר" in day[0]["title"] and day[0]["link"] == {"type": "document", "id": sv["id"]}
        assert "2026-04-26" in day[0]["text"]
        assert not [e for e in tl["events"] if e["id"] == sv["id"]]  # the notice itself is not listed twice
        home = gp.home(conn)
        w = next(x for x in home["witnesses"] if x["name"] == "אילנית פילבר")
        assert w["appearance_count"] == 1 and w["hearing_count"] == 0 and w["side"] == "defense"
        page = gp.witness_page(conn, w["slug"])
        assert page["appearances"][0]["date"] == "2026-04-20" and page["hearings"] == []


def test_model_dates_are_normalised():
    v = briefs._valid_date
    assert [v("18.05.2021"), v("28 אפריל 2026"), v("2026-04-20"), v("20/4/2026")] == ["2021-05-18", "2026-04-28",
                                                                                      "2026-04-20", "2026-04-20"]
    assert v("1999-01-01") is None and v("") is None and v(None) is None
