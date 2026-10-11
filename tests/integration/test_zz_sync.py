"""Mirror sync endpoints: the site can list everything public and ask what changed since a moment."""

from __future__ import annotations

import datetime as dt

import pytest
from ntk_common.db import knowledge as kdb
from ntk_common.db import sync
from ntk_common.db.core import execute, scalar

pytestmark = pytest.mark.db


def test_objects_and_changes(services, ingested):
    before = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    with services.engine.begin() as conn:
        svid = scalar(conn, "SELECT source_version_id FROM ntk.hearings ORDER BY hearing_date LIMIT 1")
        hid = scalar(conn, "SELECT id FROM ntk.hearings WHERE source_version_id = :sv", {"sv": svid})
        kdb.publish_source_version(conn, svid, actor="test")
        execute(conn, "UPDATE ntk.source_versions SET publication_changed_at = now() WHERE id = :sv", {"sv": svid})
    with services.engine.connect() as conn:
        objs = sync.objects(conn)
        assert any(h["id"] == hid and h["page_count"] for h in objs["hearings"]) and objs["corpus_version"]
        ch = sync.changes(conn, before)
        assert hid in ch["hearings"] and ch["lists_changed"]
        later = sync.changes(conn, dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5))
        assert later["hearings"] == [] and later["documents"] == [] and not later["lists_changed"]


def test_deferred_digests_skip_extract_a(services, fixture_path):
    import dataclasses

    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="deferred-digest"))
    stages = {s["stage"]: s for s in job["stages"]}
    assert job["status"] == "succeeded" and stages["extract_a"]["status"] == "skipped"
    assert "deferred" in stages["extract_a"]["output"]["note"]
    out = p.rebuild_hearing_digest(stages["extract_a"]["output"]["hearing_id"])  # built later, on request
    assert out.get("digest_id"), out


def test_digest_batch_submit_and_collect(services, fixture_path):
    """Deferred hearing → batch submit (one request, run id of the direct path) → poll saves the run → the digest is
    built from the stored run without a second model call."""
    import dataclasses

    from ntk_common import batches
    from ntk_common.db.core import row
    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="batch-digest"))
    hid = {s["stage"]: s for s in job["stages"]}["extract_a"]["output"]["hearing_id"]
    with services.engine.begin() as conn:  # make it a hearing without any digest, and no stored digest answer
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'hearing' AND object_id = :h",
                {"h": hid})
        execute(conn, "UPDATE ntk.model_runs SET status = 'provider_error' WHERE task_type = 'digest'")
    out = batches.submit_digests(p, hearing_ids=[hid])
    assert out["requests"] == 1 and len(out["batches"]) == 1
    name = out["batches"][0]["name"]
    assert batches.submit_digests(p, hearing_ids=[hid])["requests"] == 0  # already in an open batch
    calls = []
    orig = p.s.runner.providers["mock"].generate_json
    p.s.runner.providers["mock"].generate_json = lambda **kw: (calls.append(kw["task_type"]), orig(**kw))[1]
    try:
        res = batches.poll(p)
    finally:
        p.s.runner.providers["mock"].generate_json = orig
    built = next(b for b in res["batches"] if b["name"] == name)["built"]
    assert built[0].get("digest_id"), built
    with services.engine.connect() as conn:
        items = row(conn, "SELECT items FROM ntk.model_batches WHERE name = :n", {"n": name})["items"]
        first = row(conn, "SELECT status FROM ntk.model_runs WHERE id = CAST(:i AS uuid)", {"i": items[0]["run_id"]})
        assert first["status"] == "succeeded"  # the first-attempt digest came from the batch
    assert calls.count("digest") <= 1  # at most the wording retry is made directly
    with services.engine.connect() as conn:
        b = row(conn, "SELECT state, finished_at FROM ntk.model_batches WHERE name = :n", {"n": name})
        assert b["finished_at"] is not None and b["state"].endswith("SUCCEEDED")
        assert batches.listing(conn)[0]["name"]
