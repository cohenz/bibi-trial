"""PostgreSQL integration: idempotency, immutability, versions, publication
boundary, bi-temporal status, Project 315 import."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from ntk_common.db import knowledge as kdb
from ntk_common.db import ops
from ntk_common.db.core import row, rows, scalar
from sqlalchemy import text

from tests.conftest import FIXTURES, ROOT, make_job

pytestmark = pytest.mark.db

TABLES = ["source_versions", "source_units", "qa_exchanges", "retrieval_chunks", "retrieval_chunk_members", "hearings",
          "entities", "generated_artifacts", "model_runs", "layer_a_versions"]


def counts(engine):
    with engine.connect() as c:
        return {t: scalar(c, f"SELECT count(*) FROM ntk.{t}") for t in TABLES}


def test_sql_stable_id_matches_python(services):
    with services.engine.connect() as c:
        v = scalar(c, "SELECT ntk.stable_id('su', ARRAY['sv_x','1','1','2','0','עו\"ד חדד'])")
    assert v == "su_b2543bbf2fc89197c12455c502"


def test_pipeline_produces_expected_objects(ingested, services):
    stages = {s["stage"]: s for s in ingested["stages"]}
    assert stages["segment"]["output"]["units"] == 41
    assert stages["pair"]["output"]["exchanges"] == 15
    assert stages["extract_a"]["output"]["digest_id"]
    with services.engine.connect() as c:
        sv = row(c, "SELECT * FROM ntk.source_versions LIMIT 1")
        assert len(sv["content_sha256"]) == 64 and sv["s3_key"].endswith(f"{sv['content_sha256']}.pdf")
        assert sv["publication_state"] == "draft"


def test_rerun_is_idempotent(ingested, services, pipeline, fixture_path):
    before = counts(services.engine)
    job_id = make_job(services, fixture_path, key="idempotency-rerun")  # brand-new job, same bytes
    job = pipeline.run_job(job_id)
    assert job["status"] == "succeeded"
    assert counts(services.engine) == before


def test_changed_bytes_create_new_version_with_supersedes(ingested, services, pipeline, tmp_path, fixture_pdf):
    changed = tmp_path / "changed.pdf"
    changed.write_bytes(fixture_pdf.replace(b"SYNTHETIC FIXTURE - fictional protocol", b"SYNTHETIC FIXTURE - corrected edition!"))
    assert changed.read_bytes() != fixture_pdf
    job = pipeline.run_job(make_job(services, str(changed), key="changed-bytes"))
    assert job["status"] == "succeeded", job["error"]
    with services.engine.connect() as c:
        vs = rows(c, "SELECT id, supersedes_id, document_id FROM ntk.source_versions ORDER BY retrieved_at")
    docs = {v["document_id"] for v in vs}
    if len(docs) == 1:  # same canonical key → same logical document
        assert len(vs) == 2 and vs[1]["supersedes_id"] == vs[0]["id"]
    # old citations still exist
    with services.engine.connect() as c:
        assert scalar(c, "SELECT count(*) FROM ntk.source_units WHERE source_version_id = :v", {"v": vs[0]["id"]}) == 41


def test_source_rows_are_immutable(ingested, services):
    with services.engine.connect() as c:
        uid = scalar(c, "SELECT id FROM ntk.source_units LIMIT 1")
        svid = scalar(c, "SELECT id FROM ntk.source_versions LIMIT 1")
    with pytest.raises(Exception, match="immutable"):
        with services.engine.begin() as c:
            c.execute(text("UPDATE ntk.source_units SET raw_text = 'x' WHERE id = :id"), {"id": uid})
    with pytest.raises(Exception, match="immutable"):
        with services.engine.begin() as c:
            c.execute(text("UPDATE ntk.source_versions SET content_sha256 = repeat('0',64) WHERE id = :id"), {"id": svid})
    with pytest.raises(Exception, match="cannot be deleted"):
        with services.engine.begin() as c:
            c.execute(text("DELETE FROM ntk.source_units WHERE id = :id"), {"id": uid})
    # normalisation refresh is allowed and keeps ids
    from ntk_common.db import sources

    with services.engine.begin() as c:
        n = sources.refresh_normalization(c, svid)
    assert n == 41


def test_audit_is_append_only(services):
    with services.engine.begin() as c:
        ops.audit(c, actor="pytest", action="t", object_type="x", object_id="1")
    with pytest.raises(Exception, match="append-only"):
        with services.engine.begin() as c:
            c.execute(text("UPDATE ntk.audit_events SET actor = 'y'"))


def test_unpublished_material_is_invisible_publicly(ingested, services):
    from ntk_common.search.base import SearchFilters, SearchRequest

    be = services.search_backend()
    with services.engine.connect() as c:
        state = scalar(c, "SELECT count(*) FROM ntk.source_versions WHERE publication_state='published'")
    if state == 0:
        assert be.search(SearchRequest("הנחיות ישירות", SearchFilters(published_only=True))).hits == []
    assert be.search(SearchRequest("הנחיות ישירות", SearchFilters(published_only=False))).hits


def test_review_and_publication_rules(ingested, services):
    s = services.settings
    with services.engine.connect() as c:
        art_id = str(scalar(c, "SELECT id FROM ntk.generated_artifacts WHERE artifact_type='summary' LIMIT 1"))
    # cannot publish before approval
    with pytest.raises(kdb.PublicationError) as e:
        with services.engine.begin() as c:
            kdb.publish_artifact(conn=c, artifact_id=art_id, actor="t", env="test", public_base_url=s.public_base_url)
    assert e.value.code == "review_required"
    with services.engine.begin() as c:
        kdb.review_artifact(c, artifact_id=art_id, decision="approve", reviewer="editor", notes=None)
    # cited sources unpublished → refused unless include_sources
    with pytest.raises(kdb.PublicationError) as e:
        with services.engine.begin() as c:
            kdb.publish_artifact(c, artifact_id=art_id, actor="t", env="test", public_base_url=s.public_base_url)
    assert e.value.code == "unpublished_object"
    # mock-generated artifacts may not be published in production
    with pytest.raises(kdb.PublicationError) as e:
        with services.engine.begin() as c:
            kdb.publish_artifact(c, artifact_id=art_id, actor="t", env="production", public_base_url=s.public_base_url,
                                 include_sources=True)
    assert "mock" in str(e.value)
    with services.engine.begin() as c:
        res = kdb.publish_artifact(c, artifact_id=art_id, actor="t", env="test", public_base_url=s.public_base_url,
                                   include_sources=True)
    assert res["review_state"] == "published" and res["corpus_version"].startswith("cv-")
    with services.engine.connect() as c:
        assert scalar(c, "SELECT count(*) FROM ntk.webhook_outbox WHERE event_type='artifact.published'") >= 1
        assert scalar(c, "SELECT count(*) FROM ntk.audit_events WHERE action='artifact.publish'") >= 1
        withdrawn_blocked = True
    with pytest.raises(kdb.PublicationError):
        with services.engine.begin() as c:
            sv = row(c, """SELECT h.source_version_id FROM ntk.hearings h JOIN ntk.generated_artifacts ga
                           ON ga.object_id = h.id WHERE ga.id = CAST(:a AS uuid)""", {"a": art_id})["source_version_id"]
            kdb.withdraw_source_version(c, sv, actor="t", reason="test")
    assert withdrawn_blocked


def test_bitemporal_claim_status(services, ingested):
    s = services.settings
    with services.engine.begin() as c:
        cid, _ = kdb.ensure_claim(c, case_id=s.case_id, slug="bitemporal-test", question="שאלה לבדיקה?",
                                  claim_type="defense_claim", stance="defense", title="בדיקה", claim_text="טענה לבדיקה")
        kdb.record_claim_status(c, claim_id=cid, status="disputed", valid_from="2021-04-12T00:00:00+00:00",
                                rationale="a", source_unit_ids=[])
    t_known = dt.datetime.now(dt.UTC)
    with services.engine.begin() as c:
        kdb.record_claim_status(c, claim_id=cid, status="weakened", valid_from="2022-05-31T00:00:00+00:00",
                                rationale="b", source_unit_ids=[])
    with services.engine.connect() as c:
        assert kdb.current_claim_status(c, cid, as_of="2021-06-01T00:00:00+00:00")["status"] == "disputed"
        assert kdb.current_claim_status(c, cid, as_of="2023-01-01T00:00:00+00:00")["status"] == "weakened"
        # what did the system know before the second write?
        assert kdb.current_claim_status(c, cid, as_of="2023-01-01T00:00:00+00:00", known_at=t_known)["status"] == "disputed"


def test_project315_import(services):
    from ntk_p315.importer import ImportFailed, import_export

    content = (FIXTURES / "project315_sample_synthetic.json").read_text(encoding="utf-8")
    with services.engine.begin() as c:
        rep = import_export(c, content=content, fmt="json", source="fixture", synthetic=True, actor="pytest")
    assert rep["imported"] == 20 and rep["failed"] == 0
    w = " ".join(rep["warnings"])
    assert "duplicate" in w and "broken URL" in w and "no linked source" in w and "netanyahu_involvement" in w
    with services.engine.connect() as c:
        ev = row(c, "SELECT * FROM ntk.project315_events WHERE external_event_id = 'SYN-007'")
        assert ev["court_record_status"] == "external" and ev["in_court_record"] is False
        assert ev["independent_verification_status"] == "unreviewed" and ev["raw_payload_sha256"]
        assert ev["date_or_range"].lower == dt.date(2015, 3, 1)
    # same export again → unchanged
    with services.engine.begin() as c:
        rep2 = import_export(c, content=content, fmt="json", source="fixture", synthetic=True, actor="pytest")
    assert rep2["unchanged"] == 20 and rep2["imported"] == 0
    # changed classification → new version + diff, not a silent overwrite
    data = json.loads(content)
    data["events"][0]["project315_classification"] = "היענות חריגה"
    with services.engine.begin() as c:
        rep3 = import_export(c, content=json.dumps(data, ensure_ascii=False), fmt="json", source="fixture-v2",
                             synthetic=True, actor="pytest")
    assert rep3["updated"] == 1 and any("classification changed" in x for x in rep3["warnings"])
    with services.engine.connect() as c:
        versions = rows(c, "SELECT diff FROM ntk.project315_event_versions v JOIN ntk.project315_events e ON e.id = v.event_id "
                           "WHERE e.external_event_id = 'SYN-001' ORDER BY v.imported_at")
    assert len(versions) == 2 and "project315_classification" in versions[1]["diff"]
    # required fields missing → failure
    with pytest.raises(ImportFailed):
        with services.engine.begin() as c:
            import_export(c, content='[{"subject": "no id"}]', fmt="json", source="bad", synthetic=True, actor="pytest")


def test_label_export_and_score(services, ingested, tmp_path):
    from ntk_common.evaluation import export_label_sample, score_labels

    out = tmp_path / "speakers.csv"
    n = export_label_sample(services.engine, kind="speakers", n=10, out=out, seed="t")
    assert n == 10
    rep = score_labels(kind="speakers", path=out)
    assert rep["labeled"] == 0 and rep["passed"] is False  # unlabeled → not measured, never "passed"


_ = Path


def test_search_bench_and_pending_suites(services, ingested, settings):
    from ntk_common.evaluation import run_search_bench, run_suite

    syn = run_search_bench(ROOT / "golden" / "search-bench-synthetic-v1.json", services=services, published_only=False)
    assert syn["summary"]["queries"] == 15
    assert 0.0 <= syn["summary"]["ndcg@10"] <= 1.0  # binary gain credited once per relevant item
    # the synthetic fixture (case 99999-01-20, dated 2021-04-12) must never count as a real pilot hearing
    pil = run_search_bench(ROOT / "golden" / "search-bench-pilot-v1.json", services=services)
    assert pil["summary"]["measured"] is False and pil["summary"]["passed"] is False
    assert "2021-04-12" in pil["summary"]["blocked_by"]
    rep = run_suite(ROOT / "golden" / "pilot-hebrew-legal-v1.json", settings=settings, engine=services.engine, services=services)
    assert rep["summary"]["measured"] is False and rep["summary"]["passed"] is False


def test_rebuild_hearing_digest_outside_job(services, pipeline, ingested):
    with services.engine.connect() as conn:
        hid = scalar(conn, "SELECT id FROM ntk.hearings ORDER BY created_at LIMIT 1")
        before = scalar(conn, "SELECT count(*) FROM ntk.generated_artifacts WHERE object_type = 'hearing' AND object_id = :h",
                        {"h": str(hid)})
    out1 = pipeline.rebuild_hearing_digest(str(hid))
    out2 = pipeline.rebuild_hearing_digest(str(hid))
    assert out1["digest_id"] == out2["digest_id"]  # same corpus + sources → same digest, no duplicate artifact
    with services.engine.connect() as conn:
        after = scalar(conn, "SELECT count(*) FROM ntk.generated_artifacts WHERE object_type = 'hearing' AND object_id = :h",
                       {"h": str(hid)})
    assert after - before <= 1
    from ntk_common.orchestrator import StageError

    with pytest.raises(StageError):
        pipeline.rebuild_hearing_digest("00000000-0000-0000-0000-000000000000")


def test_verify_rechecks_mock_verdicts_after_model_switch(services, pipeline, ingested):
    """After switching from the mock provider to a real one, a re-run of `verify` replaces mock verdicts on
    exchanges still awaiting review, and never touches exchanges a person already reviewed."""
    import dataclasses

    from ntk_common.llm.providers import MockProvider
    from ntk_common.llm.registry import ModelRegistry
    from ntk_common.llm.runner import ModelRunner
    from ntk_common.orchestrator import Pipeline

    job_id = str(ingested["id"])
    with services.engine.connect() as conn:
        hid = scalar(conn, """SELECT checkpoint->>'hearing_id' FROM ntk.ingestion_job_stages
                              WHERE job_id = CAST(:j AS uuid) AND stage = 'segment'""", {"j": job_id})
    with services.engine.begin() as conn:
        exs = rows(conn, """SELECT x.id, x.review_state::text AS st, mr.provider FROM ntk.qa_exchanges x
                            LEFT JOIN ntk.model_runs mr ON mr.id = x.relation_model_run_id
                            WHERE x.hearing_id = :h AND x.public_wording IS NOT NULL ORDER BY x.id""", {"h": hid})
        assert len(exs) >= 2, "fixture should produce exchanges with public wording"
        assert all(e["st"] == "human_review_required" and e["provider"] == "mock" for e in exs)
        reviewed = exs[0]["id"]
        conn.execute(text("UPDATE ntk.qa_exchanges SET review_state = 'approved' WHERE id = :id"), {"id": reviewed})

    # the mock run itself must not re-check (nothing changed)
    with services.engine.begin() as conn:
        ops.reset_stages(conn, str(job_id), ["verify"])
    out = pipeline.run_job(str(job_id))
    assert out["status"] == "succeeded"
    with services.engine.connect() as conn:
        verify_out = scalar(conn, """SELECT output FROM ntk.ingestion_job_stages WHERE job_id = CAST(:j AS uuid)
                                     AND stage = 'verify'""", {"j": str(job_id)})
    assert verify_out["checked"] == 0

    specs = {r: services.registry.get(r) for r in ("extractor", "mapper", "judicial_classifier", "writer", "qa_relation",
                                                   "verifier", "embedder")}
    specs["verifier"] = dataclasses.replace(specs["verifier"], provider="gemini", model_family="google-gemini",
                                            model_id="gemini-test-verifier")
    registry = ModelRegistry(specs)
    runner = ModelRunner(registry, {"mock": MockProvider(), "gemini": MockProvider()}, ops.PgRunStore(services.engine))
    real = Pipeline(dataclasses.replace(services, registry=registry, runner=runner))
    with services.engine.begin() as conn:
        ops.reset_stages(conn, str(job_id), ["verify"])
    assert real.run_job(str(job_id))["status"] == "succeeded"
    with services.engine.connect() as conn:
        verify_out = scalar(conn, """SELECT output FROM ntk.ingestion_job_stages WHERE job_id = CAST(:j AS uuid)
                                     AND stage = 'verify'""", {"j": str(job_id)})
        after = {e["id"]: e for e in rows(conn, """SELECT x.id, x.review_state::text AS st, mr.provider
                    FROM ntk.qa_exchanges x LEFT JOIN ntk.model_runs mr ON mr.id = x.relation_model_run_id
                    WHERE x.hearing_id = :h AND x.public_wording IS NOT NULL""", {"h": hid})}
    assert verify_out["checked"] == len(exs) - 1 and verify_out["verifier_model"] == "gemini-test-verifier"
    assert sum(verify_out["relation_pairs"].values()) == len(exs) - 1
    assert after[reviewed]["st"] == "approved" and after[reviewed]["provider"] == "mock"
    for e in exs[1:]:
        # the placeholder verdict was replaced by a run from the real provider
        assert after[e["id"]]["provider"] == "gemini"
    # a second real re-run finds nothing left to re-check
    with services.engine.begin() as conn:
        ops.reset_stages(conn, str(job_id), ["verify"])
        conn.execute(text("UPDATE ntk.qa_exchanges SET review_state = 'human_review_required' WHERE id = :id"), {"id": reviewed})
    real.run_job(str(job_id))
    with services.engine.connect() as conn:
        assert scalar(conn, """SELECT output FROM ntk.ingestion_job_stages WHERE job_id = CAST(:j AS uuid)
                               AND stage = 'verify'""", {"j": str(job_id)})["checked"] == 1


def test_auto_publish_policy_and_label_policy(services, pipeline, ingested):
    """NTK_AUTO_PUBLISH=gates: a digest that passes every gate publishes itself once its sources are published; Q/A
    labels the verifier agrees with become machine_verified; no review task is opened for exchanges."""
    import dataclasses

    from ntk_common.orchestrator import Pipeline

    job_id = str(ingested["id"])
    with services.engine.connect() as conn:
        hid = scalar(conn, """SELECT checkpoint->>'hearing_id' FROM ntk.ingestion_job_stages
                              WHERE job_id = CAST(:j AS uuid) AND stage = 'segment'""", {"j": job_id})
        svid = scalar(conn, "SELECT source_version_id FROM ntk.hearings WHERE id = :h", {"h": hid})
    cfg = dataclasses.replace(services.settings, auto_publish="gates")
    auto = Pipeline(dataclasses.replace(services, settings=cfg))
    with services.engine.begin() as conn:
        conn.execute(text("UPDATE ntk.source_versions SET publication_state = 'draft' WHERE id = :s"), {"s": svid})
    out = auto.rebuild_hearing_digest(hid)
    assert out["auto_published"] is False  # sources not published → stays for review, nothing leaks
    with services.engine.begin() as conn:
        kdb.publish_source_version(conn, svid, actor="test")
    out = auto.rebuild_hearing_digest(hid)
    assert out["state"] == "machine_verified" and out["auto_published"] is True
    with services.engine.connect() as conn:
        art = row(conn, "SELECT review_state::text AS s FROM ntk.generated_artifacts WHERE id = CAST(:a AS uuid)",
                  {"a": out["artifact_id"]})
        assert art["s"] == "published"
        assert scalar(conn, "SELECT count(*) FROM ntk.audit_events WHERE actor = 'policy:auto-publish-gates'") >= 1
        assert scalar(conn, """SELECT count(*) FROM ntk.review_tasks WHERE object_type = 'artifact'
                               AND object_id = :a AND status = 'open'""", {"a": out["artifact_id"]}) == 0
    # labels: re-run verify under the policy
    with services.engine.begin() as conn:
        conn.execute(text("UPDATE ntk.qa_exchanges SET review_state = 'draft' WHERE hearing_id = :h AND public_wording IS NOT NULL"),
                     {"h": hid})
        open_before = scalar(conn, "SELECT count(*) FROM ntk.review_tasks WHERE object_type = 'qa_exchange' AND status = 'open'")
        ops.reset_stages(conn, job_id, ["verify"])
    assert auto.run_job(job_id)["status"] == "succeeded"
    with services.engine.connect() as conn:
        v = scalar(conn, """SELECT output FROM ntk.ingestion_job_stages WHERE job_id = CAST(:j AS uuid) AND stage = 'verify'""",
                   {"j": job_id})
        verified = scalar(conn, """SELECT count(*) FROM ntk.qa_exchanges WHERE hearing_id = :h AND review_state = 'machine_verified'""",
                          {"h": hid})
        open_after = scalar(conn, "SELECT count(*) FROM ntk.review_tasks WHERE object_type = 'qa_exchange' AND status = 'open'")
    assert v["label_policy"] == "agreement" and verified == v["verifier_agrees"]
    assert open_after == open_before


def test_reparse_supersedes_units_exchanges_and_chunks(services, ingested):
    """A re-parse never deletes citation units: units it no longer produces are superseded (excluded from listings,
    search and new AI input) but still resolve by id; producing them again makes them current again."""
    from ntk_common.db import sources
    from ntk_common.db.public import units_by_ids
    from ntk_common.search.base import SearchFilters, SearchRequest

    job_id = str(ingested["id"])
    with services.engine.connect() as conn:
        hid = scalar(conn, """SELECT checkpoint->>'hearing_id' FROM ntk.ingestion_job_stages
                              WHERE job_id = CAST(:j AS uuid) AND stage = 'segment'""", {"j": job_id})
        svid = scalar(conn, "SELECT source_version_id FROM ntk.hearings WHERE id = :h", {"h": hid})
        all_ids = [r["id"] for r in sources.units_for_version(conn, svid)]
        ex_ids = [r["id"] for r in rows(conn, "SELECT id FROM ntk.qa_exchanges WHERE hearing_id = :h AND superseded_at IS NULL", {"h": hid})]
        chunk_ids = [r["id"] for r in rows(conn, "SELECT id FROM ntk.retrieval_chunks WHERE source_version_id = :s", {"s": svid})]
    gone = all_ids[:3]
    with services.engine.begin() as conn:
        assert sources.supersede_units(conn, svid, all_ids[3:], "protocol-parser-test") == 3
        assert sources.supersede_exchanges(conn, hid, ex_ids[1:]) == 1
        assert sources.drop_stale_chunks(conn, svid, chunk_ids[1:]) == 1
    with services.engine.connect() as conn:
        current = [r["id"] for r in sources.units_for_version(conn, svid)]
        assert current == all_ids[3:]
        assert set(units_by_ids(conn, gone, published_only=False)) == set(gone)  # old citations still resolve
        assert scalar(conn, "SELECT parser_version FROM ntk.source_versions WHERE id = :s", {"s": svid}) == "protocol-parser-test"
    hits = services.search_backend(use_vector=False).search(SearchRequest(" ".join(services.engine.connect().execute(
        text("SELECT raw_text FROM ntk.source_units WHERE id = :i"), {"i": gone[0]}).scalar().split()[:4]),
        SearchFilters(published_only=False), limit=50)).hits
    assert not {h.source_unit_id for h in hits} & set(gone)
    with services.engine.begin() as conn:  # the parser produces them again → current again
        assert sources.supersede_units(conn, svid, all_ids, "protocol-parser-1.3") == 0
        sources.supersede_exchanges(conn, hid, ex_ids)
    with services.engine.connect() as conn:
        assert [r["id"] for r in sources.units_for_version(conn, svid)] == all_ids


def test_digest_waiting_for_its_source_is_published_with_it(services, ingested):
    import dataclasses

    from ntk_common.orchestrator import Pipeline

    job_id = str(ingested["id"])
    with services.engine.connect() as conn:
        hid = scalar(conn, """SELECT checkpoint->>'hearing_id' FROM ntk.ingestion_job_stages
                              WHERE job_id = CAST(:j AS uuid) AND stage = 'segment'""", {"j": job_id})
        svid = scalar(conn, "SELECT source_version_id FROM ntk.hearings WHERE id = :h", {"h": hid})
    auto = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, auto_publish="gates")))
    with services.engine.begin() as conn:
        conn.execute(text("UPDATE ntk.source_versions SET publication_state = 'draft' WHERE id = :s"), {"s": svid})
        conn.execute(text("""UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'hearing'
                             AND object_id = :h AND review_state = 'published'"""), {"h": hid})
        conn.execute(text("UPDATE ntk.publications SET unpublished_at = now() WHERE unpublished_at IS NULL"))
    out = auto.rebuild_hearing_digest(hid)
    if out.get("state") != "machine_verified":
        pytest.skip("mock digest did not pass the gates on this fixture")
    assert out["auto_published"] is False
    with services.engine.begin() as conn:
        kdb.publish_source_version(conn, svid, actor="test")
    assert auto.auto_publish_latest(object_type="hearing", object_id=hid) is True
    with services.engine.connect() as conn:
        assert scalar(conn, "SELECT review_state::text FROM ntk.generated_artifacts WHERE id = CAST(:a AS uuid)",
                      {"a": out["artifact_id"]}) == "published"


def test_repair_keeps_same_pair_when_exchange_id_changes(services, pipeline, ingested):
    """Re-running `pair` after a parser change that alters an exchange's id (not its question/answer) must not fail on
    the (question, answer) uniqueness and must keep the pair current."""
    job_id = str(ingested["id"])
    with services.engine.begin() as conn:
        hid = scalar(conn, """SELECT checkpoint->>'hearing_id' FROM ntk.ingestion_job_stages
                              WHERE job_id = CAST(:j AS uuid) AND stage = 'segment'""", {"j": job_id})
        before = scalar(conn, "SELECT count(*) FROM ntk.qa_exchanges WHERE hearing_id = :h AND superseded_at IS NULL", {"h": hid})
        # simulate ids minted by an older parser
        conn.execute(text("ALTER TABLE ntk.qa_exchanges DISABLE TRIGGER ALL"))
        conn.execute(text("UPDATE ntk.qa_exchanges SET id = 'qx_' || substr(md5(id), 1, 26) WHERE hearing_id = :h"), {"h": hid})
        conn.execute(text("ALTER TABLE ntk.qa_exchanges ENABLE TRIGGER ALL"))
        ops.reset_stages(conn, job_id, ["pair"])
    assert pipeline.run_job(job_id)["status"] == "succeeded"
    with services.engine.connect() as conn:
        after = scalar(conn, "SELECT count(*) FROM ntk.qa_exchanges WHERE hearing_id = :h AND superseded_at IS NULL", {"h": hid})
    assert after == before


def test_surrounding_passages_in_reading_order(ingested, services):
    """16.10.2026: the Ask writer gets the passages around an exchange (PgAskStore.surrounding)."""
    import sqlalchemy as sa
    from ntk_common.db.public import PgAskStore

    with services.engine.begin() as conn:
        sv = conn.execute(sa.text("SELECT source_version_id FROM ntk.source_units GROUP BY 1 ORDER BY count(*) DESC LIMIT 1")).scalar()
        conn.execute(sa.text("UPDATE ntk.source_versions SET publication_state = 'published' WHERE id = :sv"), {"sv": sv})
        order = [r[0] for r in conn.execute(sa.text(
            "SELECT id FROM ntk.source_units WHERE source_version_id = :sv AND superseded_at IS NULL "
            "ORDER BY page_no, line_start, unit_ordinal"), {"sv": sv})]
    assert len(order) >= 6
    mid = order[3]
    got = PgAskStore(services.engine, case_id="x").surrounding([mid, order[0]], before=2, after=2)
    assert got[mid] == (order[1:3], order[4:6])
    assert got[order[0]] == ([], order[1:3])
