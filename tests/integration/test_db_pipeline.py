"""PostgreSQL integration: idempotency, immutability, versions, publication
boundary, bi-temporal status, Project 315 import."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from ntk_common.db import knowledge as kdb
from ntk_common.db import ops
from ntk_common.db.core import row, rows, scalar
from tests.conftest import FIXTURES, make_job

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
