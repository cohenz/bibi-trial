"""Reader guides end to end with the mock provider: indictment → case guides and overview, witness guide from a hearing,
review, publication and the public read models (ADR-0015)."""

from __future__ import annotations

import pytest
from ntk_common import guide_service, inbox
from ntk_common.db import guides_public as gp
from ntk_common.db import knowledge as kdb
from ntk_common.db.core import row, rows, scalar
from ntk_common.jobs import TASK_RUN_JOB, InlineQueue

pytest.importorskip("reportlab", reason="synthetic document PDFs are drawn with reportlab (dev dependency)")
from tests.doc_fixtures import INDICTMENT, make_pdf  # noqa: E402

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def built(services, pipeline, ingested):
    services.storage.put_bytes("inbox-guides/indictment.pdf", make_pdf(INDICTMENT), mime_type="application/pdf")
    sid = inbox.start_scan(services.engine, trigger="test")
    res = inbox.list_new(services, prefix="inbox-guides/", scan_id=sid)
    for iid in res["pending_ids"]:
        inbox.classify_item(services, iid)
    q = InlineQueue({TASK_RUN_JOB: lambda jid: pipeline.run_job(jid)})
    inbox.queue_items(services, q, task_name=TASK_RUN_JOB, item_ids=res["pending_ids"])
    with services.engine.begin() as conn:
        it = row(conn, "SELECT * FROM ntk.inbox_items WHERE object_key = 'inbox-guides/indictment.pdf'")
        assert it["doc_kind"] == "indictment"
        svid = scalar(conn, "SELECT id FROM ntk.source_versions WHERE content_sha256 = :s", {"s": it["content_sha256"]})
        kdb.publish_source_version(conn, svid, actor="test")
        hsv = scalar(conn, "SELECT source_version_id FROM ntk.hearings ORDER BY hearing_date LIMIT 1")
        kdb.publish_source_version(conn, hsv, actor="test")
    out = guide_service.build(pipeline, kind="all", source_version_id=svid)
    return svid, out


def test_indictment_sections_and_guides_built(built):
    svid, out = built
    assert out["indictment"]["source_version_id"] == svid
    assert set(out["indictment"]["counts"]) == {"4000", "2000"} and out["indictment"]["appendices"] == {"4000": 1}
    objs = {b["object"]: b for b in out["built"]}
    assert {"indictment:main", "case:4000", "case:2000"} <= set(objs)
    for k in ("indictment:main", "case:4000", "case:2000"):
        assert objs[k]["state"] == "human_review_required", objs[k]  # a person approves every guide once
        assert objs[k]["items"] > 0
    assert any(k.startswith("witness:w_") for k in objs)


def test_case_guide_payload_cites_the_indictment(services, built):
    svid, _ = built
    with services.engine.connect() as conn:
        art = row(conn, """SELECT payload, review_state::text AS st FROM ntk.generated_artifacts
                           WHERE artifact_type = 'guide' AND object_type = 'case' AND object_id = '4000'
                           ORDER BY created_at DESC LIMIT 1""")
        cited_svs = {r["sv"] for r in rows(conn, """SELECT DISTINCT su.source_version_id AS sv FROM ntk.artifact_citations ac
            JOIN ntk.source_units su ON su.id = ac.source_unit_id JOIN ntk.generated_artifacts ga ON ga.id = ac.artifact_id
            WHERE ga.artifact_type = 'guide' AND ga.object_type = 'case'""")}
    p = art["payload"]
    assert p["kind"] == "case" and p["title"] == "תיק 4000" and cited_svs == {svid}
    events = next(b for b in p["blocks"] if b["block"] == "events")["items"]
    assert [e["date"] for e in events] == sorted(e["date"] for e in events) and events[0]["date"] == "2015-03-12"
    assert all(e["date_precision"] == "day" and e["case_keys"] == ["4000"] for e in events)


def test_nothing_public_before_approval_then_pages_after(services, built):
    with services.engine.connect() as conn:
        home = gp.home(conn)
        assert home["indictment"] is None and home["cases"] == []
        assert home["witnesses"], "witnesses come from published hearings, guides or not"
        assert gp.case_page(conn, "4000") is None
    with services.engine.begin() as conn:
        for a in rows(conn, """SELECT id::text AS id FROM ntk.generated_artifacts
                               WHERE artifact_type = 'guide' AND review_state = 'human_review_required'"""):
            kdb.review_artifact(conn, artifact_id=a["id"], decision="approve", reviewer="test", notes=None)
            kdb.publish_artifact(conn, artifact_id=a["id"], actor="test", env="test", public_base_url="http://t")
    with services.engine.connect() as conn:
        home = gp.home(conn)
        assert home["indictment"]["document"]["page_count"] == 2
        assert [c["key"] for c in home["cases"]] == ["4000", "2000"]
        assert home["cases"][0]["one_line"]["citation_ids"]
        case = gp.case_page(conn, "4000")
        assert case["document"]["source_version_id"] == built[0]
        tl = gp.timeline(conn)
        story = [e for e in tl["events"] if e["track"] == "story"]
        trial = [e for e in tl["events"] if e["track"] == "trial"]
        assert story and all(set(e["citation_ids"]) <= set(tl["citations"]) for e in story)
        assert any(e["kind"] == "hearing" for e in trial) and any(e["kind"] == "indictment" for e in trial)
        w = home["witnesses"][0]
        page = gp.witness_page(conn, w["slug"])
        assert page["name"] == w["name"] and page["hearings"]
        assert page["artifact_id"] and any(b["block"] == "testimony" for b in page["blocks"])
        assert gp.witness_page(conn, "w_0000000000") is None


def test_witness_guide_through_batch(services, pipeline, built):
    """A witness without a guide → batch submit with the direct path's run id → poll saves the run → the guide is
    built from the stored run, without a direct witness_guide call."""
    from ntk_common import batches
    from ntk_common.db.core import execute

    slug = next(b["object"].split(":", 1)[1] for b in built[1]["built"] if b["object"].startswith("witness:"))
    with services.engine.begin() as conn:
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'witness' AND object_id = :s",
                {"s": slug})
        execute(conn, "UPDATE ntk.model_runs SET status = 'provider_error' WHERE task_type = 'witness_guide'")
        execute(conn, "UPDATE ntk.model_batches SET finished_at = now() WHERE finished_at IS NULL")
    out = batches.submit(pipeline, "witness_guide", keys=[slug])
    assert out["requests"] == 1 and len(out["batches"]) == 1, out
    assert batches.submit(pipeline, "witness_guide", keys=[slug])["requests"] == 0  # already in an open batch
    calls = []
    prov = pipeline.s.runner.providers["mock"]
    orig = prov.generate_json
    prov.generate_json = lambda **kw: (calls.append(kw["task_type"]), orig(**kw))[1]
    try:
        res = batches.poll(pipeline)
    finally:
        prov.generate_json = orig
    built_ = next(b for b in res["batches"] if b["name"] == out["batches"][0]["name"])["built"]
    assert built_[0].get("artifact_id") and built_[0]["via"] == "batch", built_
    assert calls.count("witness_guide") <= 1  # at most the wording retry is made directly
    with services.engine.connect() as conn:
        run_id = row(conn, "SELECT items FROM ntk.model_batches WHERE name = :n", {"n": out["batches"][0]["name"]})["items"][0]["run_id"]
        assert row(conn, "SELECT status FROM ntk.model_runs WHERE id = CAST(:i AS uuid)", {"i": run_id})["status"] == "succeeded"
        assert row(conn, "SELECT count(*) AS n FROM ntk.generated_artifacts WHERE id = CAST(:a AS uuid)",
                   {"a": built_[0]["artifact_id"]})["n"] == 1


def test_witness_policy_publishes_clean_guides_and_keeps_holds(services, pipeline, built, monkeypatch):
    """Operator policy (13.10.2026): a waiting witness guide that passes is published by the policy; a held one waits,
    with the reason on its review task; a release lets it through."""
    import dataclasses

    from ntk_common.db.core import execute
    from ntk_common.orchestrator import Pipeline

    slug = next(b["object"].split(":", 1)[1] for b in built[1]["built"] if b["object"].startswith("witness:"))
    gp_ = Pipeline(services)
    gp_.cfg = dataclasses.replace(services.settings, auto_publish="gates")

    def waiting_copy():
        with services.engine.begin() as conn:
            a = row(conn, """SELECT id::text AS id FROM ntk.generated_artifacts WHERE object_type = 'witness' AND object_id = :s
                             ORDER BY created_at DESC LIMIT 1""", {"s": slug})
            if scalar(conn, "SELECT review_state::text FROM ntk.generated_artifacts WHERE id = CAST(:a AS uuid)", {"a": a["id"]}) == "published":
                kdb.unpublish_artifact(conn, artifact_id=a["id"], actor="test", reason="test")
            execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'human_review_required' WHERE id = CAST(:a AS uuid)",
                    {"a": a["id"]})
            kdb.open_review_task(conn, object_type="artifact", object_id=a["id"], risk_flags=[], reason="guide for test")
        return a["id"]

    aid = waiting_copy()
    dry = guide_service.apply_witness_policy(gp_, keys=[slug], holds={slug: "עדות פרוצדורלית בלבד"})
    assert dry["counts"]["waits"] == 1 and dry["waits"][0]["reason"] == "עדות פרוצדורלית בלבד"
    with services.engine.connect() as conn:  # a dry run records nothing
        assert guide_service._hold(conn, slug) is None
    out = guide_service.apply_witness_policy(gp_, holds={slug: "עדות פרוצדורלית בלבד"}, apply=True, actor="test")
    assert slug in {w["slug"] for w in out["waits"]}
    with services.engine.connect() as conn:
        t = row(conn, "SELECT reason FROM ntk.review_tasks WHERE object_id = :a AND status = 'open'", {"a": aid})
        assert t["reason"].endswith(" — עדות פרוצדורלית בלבד")
    # a rebuild of a held witness waits too
    rebuilt = guide_service.build(gp_, kind="witnesses", keys=[slug])["built"][0]
    assert rebuilt["state"] != "published" and rebuilt.get("waits") == "עדות פרוצדורלית בלבד"
    from ntk_common import guides

    monkeypatch.setattr(guides, "MIN_TESTIMONY_ITEMS", 1)  # the mock writes a two-sentence guide
    out = guide_service.apply_witness_policy(gp_, keys=[slug], release=[slug], apply=True, actor="test")
    assert out["counts"]["published"] == 1 and out["published"][0]["published"] is True, out
    with services.engine.connect() as conn:
        pub = rows(conn, """SELECT id::text AS id, gate_report FROM ntk.generated_artifacts WHERE object_type = 'witness'
                            AND object_id = :s AND review_state = 'published'""", {"s": slug})
        assert len(pub) == 1
        assert row(conn, "SELECT decided_by FROM ntk.review_tasks WHERE object_id = :a ORDER BY completed_at DESC NULLS LAST LIMIT 1",
                   {"a": pub[0]["id"]})["decided_by"] == "policy:auto-publish-gates"
        assert row(conn, "SELECT count(*) AS n FROM ntk.review_tasks WHERE object_id = :a AND status = 'open'",
                   {"a": pub[0]["id"]})["n"] == 0
        assert gp.witness_page(conn, slug)["artifact_id"] == pub[0]["id"]
