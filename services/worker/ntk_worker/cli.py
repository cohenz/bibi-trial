"""`trial-knowledge` command line (spec §34.2).

  trial-knowledge migrate
  trial-knowledge ingest manifests/pilot-april-2021.json [--inline]
  trial-knowledge run --stage parse,pair,chunk,extract-a,map-b,verify --manifest manifests/pilot-april-2021.json
  trial-knowledge seed-claims
  trial-knowledge build-claims --slug fixture-instructions
  trial-knowledge eval --suite golden/pilot-hebrew-legal-v1.json
  trial-knowledge bench --suite golden/search-bench-v1.json
  trial-knowledge publish --artifact-set pilot-april-2021 --dry-run
  trial-knowledge p315-import FILE [--mapping mapping.json] [--synthetic]
  trial-knowledge label-export --kind speakers --n 200 --out golden/labels/speakers.csv
  trial-knowledge label-score --kind speakers --file golden/labels/speakers.csv
  trial-knowledge openapi --out contracts/openapi.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parents[3]

STAGE_ALIASES = {
    "register": ["register"], "download": ["download"], "validate": ["validate"],
    "parse": ["extract_text", "ocr_fallback", "lineize", "segment"], "extract": ["extract_text", "ocr_fallback", "lineize"],
    "segment": ["segment"], "pair": ["pair"], "chunk": ["chunk"], "embed": ["embed"],
    "extract-a": ["extract_a"], "extract_a": ["extract_a"], "map-b": ["map_b"], "map_b": ["map_b"],
    "verify": ["verify"], "review": ["review"], "publish": ["publish"],
}


def _ctx():
    from ntk_common.config import get_settings
    from ntk_common.db.core import get_engine
    from ntk_common.orchestrator import Pipeline, build_services

    s = get_settings()
    eng = get_engine(s.database_url)
    services = build_services(s, eng)
    return s, eng, services, Pipeline(services)


def _load_manifest(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.setdefault("name", Path(path).stem)
    base = Path(path).resolve().parent
    for d in data.get("documents", []):
        if d.get("local_path") and not os.path.isabs(d["local_path"]):
            d["local_path"] = str((base / d["local_path"]).resolve())
    return data


@click.group()
def main() -> None:
    """Netanyahu trial knowledge base — operations CLI."""


@main.command()
@click.option("--revision", default="head")
def migrate(revision: str) -> None:
    """Apply database migrations (Alembic, SQL-first)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "db" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "db" / "alembic"))
    command.upgrade(cfg, revision)
    click.echo(f"migrated to {revision}")


@main.command()
@click.argument("manifest")
@click.option("--inline/--queue", default=False, help="run the pipeline in this process instead of the worker queue")
@click.option("--stop-after", default=None)
def ingest(manifest: str, inline: bool, stop_after: str | None) -> None:
    """Create (idempotent) ingestion jobs for every document in a manifest."""
    from ntk_common.db import ops
    from ntk_common.jobs import TASK_RUN_JOB, CeleryQueue
    from ntk_common.orchestrator import doc_input_from_manifest, job_idempotency_key

    s, eng, services, pipe = _ctx()
    m = _load_manifest(manifest)
    m.setdefault("case_id", s.case_id)
    q = None if inline else CeleryQueue(s.redis_url)
    with eng.begin() as conn:
        ops.sync_registry(conn, services.registry.rows())
    for doc in m["documents"]:
        inp = doc_input_from_manifest(m, doc)
        with eng.begin() as conn:
            job, created = ops.create_job(conn, idempotency_key=job_idempotency_key(inp), input_=inp, requested_by="cli")
            ops.audit(conn, actor="cli", action="ingestion_job.create", object_type="ingestion_job", object_id=str(job["id"]),
                      details={"manifest": m["name"], "created": created})
        click.echo(f"{doc.get('hearing_date')}  job={job['id']}  created={created}")
        if inline:
            res = pipe.run_job(str(job["id"]), stop_after=stop_after)
            click.echo(f"   → {res['status']}" + (f"  error={res['error']}" if res.get("error") else ""))
        elif created:
            q.enqueue(TASK_RUN_JOB, str(job["id"]))  # type: ignore[union-attr]


@main.command()
@click.option("--stage", "stages", required=True, help="comma list, e.g. parse,pair,chunk,extract-a,map-b,verify")
@click.option("--manifest", required=True)
def run(stages: str, manifest: str) -> None:
    """Run (or re-run) selected stages for every job of a manifest, inline."""
    from ntk_common.db import ops
    from ntk_common.db.core import execute
    from ntk_common.orchestrator import doc_input_from_manifest, job_idempotency_key

    s, eng, services, pipe = _ctx()
    m = _load_manifest(manifest)
    m.setdefault("case_id", s.case_id)
    wanted: list[str] = []
    for token in stages.split(","):
        token = token.strip()
        if token not in STAGE_ALIASES:
            raise click.BadParameter(f"unknown stage {token}; valid: {sorted(STAGE_ALIASES)}")
        wanted += STAGE_ALIASES[token]
    for doc in m["documents"]:
        inp = doc_input_from_manifest(m, doc)
        with eng.begin() as conn:
            job, _ = ops.create_job(conn, idempotency_key=job_idempotency_key(inp), input_=inp, requested_by="cli")
            # explicit re-run: mark the requested stages pending (checkpoints of other stages stay)
            execute(conn, """UPDATE ntk.ingestion_job_stages SET status = 'pending'
                             WHERE job_id = CAST(:j AS uuid) AND stage = ANY(:st)""", {"j": str(job["id"]), "st": wanted})
        prereq = ["register", "download", "validate"]
        res = pipe.run_job(str(job["id"]), only=prereq + wanted)
        click.echo(f"{doc.get('hearing_date')}  job={job['id']}  → " +
                   ", ".join(f"{x['stage']}:{x['status']}" for x in res["stages"] if x["stage"] in wanted))


@main.command("seed-claims")
@click.option("--file", "path", default=str(ROOT / "manifests" / "claims-registry-v1.json"))
def seed_claims(path: str) -> None:
    """Load the thesis registry (spec §8, T01–T17) as draft claims."""
    from ntk_common.db import knowledge as kdb
    from ntk_common.db import ops

    s, eng, _, _ = _ctx()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    with eng.begin() as conn:
        from ntk_common.db import sources

        sources.ensure_case(conn, case_id=s.case_id, court_case_number=s.court_case_number,
                            title="מדינת ישראל נ' נתניהו ואח'", court_name="בית המשפט המחוזי בירושלים")
        for c in data["claims"]:
            cid, vid = kdb.ensure_claim(conn, case_id=s.case_id, slug=c["slug"], question=c["question"],
                                        claim_type=c["claim_type"], stance=c.get("stance"), title=c["title"],
                                        claim_text=c["claim_text"], editorial_priority=c.get("editorial_priority", 0),
                                        thesis_code=c.get("thesis_code"), sensitivity=c.get("sensitivity", []),
                                        disclosure=c.get("disclosure"), created_by="cli")
            click.echo(f"{c.get('thesis_code', ''):4} {c['slug']:40} {cid}")
        for e in data.get("case_events", []):
            kdb.add_case_event(conn, case_id=s.case_id, event_type=e["event_type"], occurred_at=e["occurred_at"],
                               title=e["title"], description=e.get("description"), outcome=e.get("outcome"),
                               external_sources=e.get("external_sources"), review_state=e.get("review_state", "draft"),
                               actor="cli")
        ops.audit(conn, actor="cli", action="claims.seed", object_type="claims", object_id=None, details={"file": path})


@main.command("build-claims")
@click.option("--slug", "slugs", multiple=True)
@click.option("--all-claims", is_flag=True)
def build_claims(slugs: tuple[str, ...], all_claims: bool) -> None:
    from ntk_common.db import knowledge as kdb

    s, eng, _, pipe = _ctx()
    with eng.connect() as conn:
        claims = kdb.list_claims(conn)
    for c in claims:
        if all_claims or c["slug"] in slugs:
            click.echo(json.dumps(pipe.build_claim(str(c["id"])), ensure_ascii=False))


@main.command()
@click.option("--artifact-set", required=True, help="manifest name whose hearings/claims to publish, or 'all'")
@click.option("--dry-run/--apply", default=True)
@click.option("--include-sources", is_flag=True)
def publish(artifact_set: str, dry_run: bool, include_sources: bool) -> None:
    """Publish APPROVED artifacts of an artifact set (never unapproved ones)."""
    from ntk_common.db import knowledge as kdb
    from ntk_common.db.core import rows

    s, eng, _, _ = _ctx()
    with eng.connect() as conn:
        arts = rows(conn, """
            SELECT ga.id, ga.artifact_type, ga.object_type, ga.object_id, ga.review_state FROM ntk.generated_artifacts ga
            WHERE ga.review_state IN ('approved','machine_verified','human_review_required','published')
              AND (:set = 'all' OR ga.object_id IN (
                    SELECT h.id FROM ntk.hearings h JOIN ntk.ingestion_jobs j ON j.source_version_id = h.source_version_id
                    WHERE j.input->>'manifest' = :set)
                OR ga.object_type = 'claim')
            ORDER BY ga.created_at
        """, {"set": artifact_set})
    for a in arts:
        verdict = "publish" if a["review_state"] == "approved" else ("already published" if a["review_state"] == "published"
                                                                    else f"skip ({a['review_state']}: needs approval)")
        click.echo(f"{a['artifact_type']:10} {a['object_id']:40} {verdict}")
        if not dry_run and a["review_state"] == "approved":
            with eng.begin() as conn:
                try:
                    r = kdb.publish_artifact(conn, artifact_id=str(a["id"]), actor="cli", env=s.env,
                                             public_base_url=s.public_base_url, include_sources=include_sources)
                    click.echo(f"   published → {r['corpus_version']}")
                except kdb.PublicationError as exc:
                    click.echo(f"   refused: {exc.code}: {exc}")
    if dry_run:
        click.echo("dry run: nothing published")


@main.command()
@click.option("--suite", required=True)
@click.option("--out", default=None)
def eval(suite: str, out: str | None) -> None:  # noqa: A001 - spec command name
    """Run a golden question suite through Ask the Trial and score it."""
    from ntk_common.evaluation import run_suite

    s, eng, services, _ = _ctx()
    report = run_suite(Path(suite), settings=s, engine=eng, services=services)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    click.echo(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not report["summary"]["passed"]:
        sys.exit(1)


@main.command()
@click.option("--suite", required=True)
@click.option("--out", default=None)
@click.option("--published-only/--all-sources", default=False)
def bench(suite: str, out: str | None, published_only: bool) -> None:
    """Search benchmark: Recall@20, nDCG@10, latency."""
    from ntk_common.evaluation import run_search_bench

    s, eng, services, _ = _ctx()
    report = run_search_bench(Path(suite), services=services, published_only=published_only)
    if out:
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(json.dumps(report["summary"], ensure_ascii=False, indent=2))


@main.command("p315-import")
@click.argument("file")
@click.option("--mapping", default=None, help="JSON mapping file canonical_field → source column")
@click.option("--synthetic", is_flag=True, help="mark records as synthetic test data")
@click.option("--source", default=None)
def p315_import(file: str, mapping: str | None, synthetic: bool, source: str | None) -> None:
    from ntk_p315.importer import ImportFailed, import_export

    s, eng, _, _ = _ctx()
    content = Path(file).read_text(encoding="utf-8")
    fmt = "csv" if file.lower().endswith(".csv") else "json"
    mp = json.loads(Path(mapping).read_text(encoding="utf-8")) if mapping else None
    try:
        with eng.begin() as conn:
            rep = import_export(conn, content=content, fmt=fmt, source=source or Path(file).name, synthetic=synthetic,
                                actor="cli", mapping=mp, case_id=s.case_id)
    except ImportFailed as exc:
        click.echo(f"import failed: {exc}\n{json.dumps(exc.errors, ensure_ascii=False)[:2000]}")
        sys.exit(1)
    click.echo(json.dumps({k: v for k, v in rep.items() if k != "warnings"}, ensure_ascii=False, indent=2))
    for w in rep["warnings"][:30]:
        click.echo(f"  warning: {w}")


@main.command("label-export")
@click.option("--kind", type=click.Choice(["speakers", "exchanges", "citations"]), required=True)
@click.option("--n", default=200)
@click.option("--out", required=True)
@click.option("--seed", default="pilot-april-2021")
def label_export(kind: str, n: int, out: str, seed: str) -> None:
    """Export a deterministic random sample for human labelling."""
    from ntk_common.evaluation import export_label_sample

    s, eng, _, _ = _ctx()
    count = export_label_sample(eng, kind=kind, n=n, out=Path(out), seed=seed)
    click.echo(f"wrote {count} rows to {out}; fill the 'label_*' columns and run label-score")


@main.command("label-score")
@click.option("--kind", type=click.Choice(["speakers", "exchanges", "citations"]), required=True)
@click.option("--file", "path", required=True)
def label_score(kind: str, path: str) -> None:
    from ntk_common.evaluation import score_labels

    rep = score_labels(kind=kind, path=Path(path))
    click.echo(json.dumps(rep, ensure_ascii=False, indent=2))


@main.command()
@click.option("--out", default=str(ROOT / "contracts" / "openapi.json"))
def openapi(out: str) -> None:
    """Write the OpenAPI document of the Knowledge API."""
    from ntk_api.app import create_app

    spec = create_app().openapi()
    Path(out).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"wrote {out} ({len(spec['paths'])} paths)")


if __name__ == "__main__":
    main()
