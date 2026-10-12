"""Mirror sync endpoints: the site can list everything public and ask what changed since a moment."""

from __future__ import annotations

import datetime as dt

import pytest
from ntk_common.db import knowledge as kdb
from ntk_common.db import sync
from ntk_common.db.core import execute, j, scalar

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


def test_digest_batch_invalid_answer_falls_back_to_direct(services, fixture_path):
    """The batch endpoint may ignore the response schema: an invalid answer is not resubmitted; the hearing is built
    with one direct (schema-constrained) call, and the batch prompt carries the schema as text."""
    import dataclasses

    from ntk_common import batches
    from ntk_common.llm.providers import ProviderResult
    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    assert "<output_json_schema>" in batches.with_schema_text("u", {"type": "object"})
    assert batches.with_schema_text("u", None) == "u"
    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="batch-digest-fallback"))
    hid = {s["stage"]: s for s in job["stages"]}["extract_a"]["output"]["hearing_id"]
    with services.engine.begin() as conn:
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'hearing' AND object_id = :h",
                {"h": hid})
        execute(conn, "UPDATE ntk.model_runs SET status = 'provider_error' WHERE task_type = 'digest'")
    sent = []
    prov = p.s.runner.providers["mock"]
    orig_create, orig_get = prov.create_batch, prov.get_batch
    prov.create_batch = lambda **kw: (sent.extend(kw["items"]), orig_create(**kw))[1]
    out = batches.submit_digests(p, hearing_ids=[hid])
    name = out["batches"][0]["name"]
    assert "<output_json_schema>" in sent[0]["request"]["contents"][0]["parts"][0]["text"]
    key = sent[0]["key"]
    prov.get_batch = lambda n: {"state": "BATCH_STATE_SUCCEEDED", "done": True, "error": None,
                                "responses": {key: ProviderResult(text='{"summary": "free-form"}', usage={}, model_version="m", raw=None)}}
    try:
        res = batches.poll(p)
    finally:
        prov.create_batch, prov.get_batch = orig_create, orig_get
    built = next(b for b in res["batches"] if b["name"] == name)["built"]
    assert built[0].get("digest_id") and built[0]["via"] == "direct_fallback", built


def test_digest_batch_quota_allowance(services, fixture_path):
    """The provider refuses for quota (HTTP 429): nothing is lost — the approval is kept as an allowance and poll()
    sends it as soon as the provider accepts; never more than approved; limit=0 cancels."""
    import dataclasses

    from ntk_common import batches
    from ntk_common.llm.providers import ProviderError
    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="batch-quota"))
    hid = {s["stage"]: s for s in job["stages"]}["extract_a"]["output"]["hearing_id"]
    with services.engine.begin() as conn:
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'hearing' AND object_id = :h",
                {"h": hid})
        execute(conn, "UPDATE ntk.model_runs SET status = 'provider_error' WHERE task_type = 'digest'")
        execute(conn, "UPDATE ntk.model_batches SET finished_at = now() WHERE finished_at IS NULL")
    prov = p.s.runner.providers["mock"]
    orig_create = prov.create_batch
    full = {"on": True}
    sent: list[int] = []

    def quota(**kw):
        if full["on"]:
            raise ProviderError("gemini HTTP 429: You exceeded your current quota", retryable=True, status=429)
        sent.append(len(kw["items"]))
        return orig_create(**kw)

    prov.create_batch = quota
    try:
        out = batches.submit_digests(p, limit=3, approved_by="test")
        assert out["quota_full"] and not out["batches"] and out["not_sent_now"] == 1, out
        with services.engine.connect() as conn:
            al = batches.allowance(conn)
        assert al["remaining"] == 3 and al["approved_total"] == 3 and al["approved_by"] == "test" and "429" in al["last_error"]
        full["on"] = False
        res = batches.poll(p)  # the provider accepts now: the approved request goes out
        assert sum(x["items"] for x in res["submitted"]["batches"]) + res["submitted"]["built_directly"] == 1, res
        with services.engine.connect() as conn:
            assert batches.allowance(conn)["remaining"] == 2  # one used; no more hearings to send now
        batches.submit_digests(p, limit=0)  # cancel what is left
        with services.engine.connect() as conn:
            assert batches.allowance(conn)["remaining"] == 0
        assert sum(sent) <= 3
        batches.poll(p)  # collect the open batch so later tests start clean
    finally:
        prov.create_batch = orig_create


def test_rejected_digest_does_not_spend_an_approval(services, fixture_path):
    """A hearing whose digest was rejected is not picked by an approval (its stored answer would be rebuilt, rejected
    again and counted against the approval); it can still be retried by id."""
    import dataclasses

    from ntk_common import batches
    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="batch-rejected"))
    hid = {s["stage"]: s for s in job["stages"]}["extract_a"]["output"]["hearing_id"]
    p.rebuild_hearing_digest(hid)  # a digest artifact exists for the hearing
    with services.engine.begin() as conn:
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'rejected' WHERE object_type = 'hearing' AND object_id = :h",
                {"h": hid})
        picked = [h["id"] for h in batches._hearings_without_digest(conn, None, 500)]
        by_id = [h["id"] for h in batches._hearings_without_digest(conn, [hid], 10)]
    assert hid not in picked
    assert by_id == [hid]


def test_cached_answer_with_unknown_citation_is_not_reused(services, fixture_path):
    """A stored digest answer (e.g. from a batch) citing a passage that does not exist is checked again at reuse:
    marked invalid and asked again, instead of failing on the citation insert (12.10.2026 incident)."""
    import dataclasses

    from ntk_common.db.core import row
    from ntk_common.layers import digest_input
    from ntk_common.orchestrator import Pipeline

    from tests.conftest import make_job

    p = Pipeline(dataclasses.replace(services, settings=dataclasses.replace(services.settings, hearing_digests="deferred")))
    job = p.run_job(make_job(services, fixture_path, key="stale-answer"))
    hid = {s["stage"]: s for s in job["stages"]}["extract_a"]["output"]["hearing_id"]
    first = p.rebuild_hearing_digest(hid)
    assert first.get("digest_id"), first
    with services.engine.connect() as conn:
        svid = row(conn, "SELECT source_version_id FROM ntk.hearings WHERE id = :h", {"h": hid})["source_version_id"]
    units, exchanges, _cv = p.digest_material(hid, svid)
    req = p.s.runner.request_for("digest", digest_input(hearing_id=hid, units=units, exchanges=exchanges))
    bad = "su_" + "f" * 26
    with services.engine.begin() as conn:  # the stored answer now cites a passage that does not exist
        out = row(conn, "SELECT output FROM ntk.model_runs WHERE id = CAST(:i AS uuid)", {"i": req["run_id"]})["output"]
        out["summary_sentences"][0]["source_unit_ids"] = [bad]
        execute(conn, "UPDATE ntk.model_runs SET output = CAST(:o AS jsonb), status = 'succeeded' WHERE id = CAST(:i AS uuid)",
                {"o": j(out), "i": req["run_id"]})
        execute(conn, "UPDATE ntk.generated_artifacts SET review_state = 'superseded' WHERE object_type = 'hearing' AND object_id = :h",
                {"h": hid})
    again = p.rebuild_hearing_digest(hid)  # no IntegrityError
    assert again.get("digest_id"), again
    with services.engine.connect() as conn:
        st = row(conn, "SELECT status FROM ntk.model_runs WHERE id = CAST(:i AS uuid)", {"i": req["run_id"]})["status"]
    assert st in {"invalid_output", "succeeded"}  # marked invalid, then (mock) answered again
