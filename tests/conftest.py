"""Shared fixtures.

DB tests need a PostgreSQL 16 server with pgvector and pg_trgm. Set
NTK_TEST_ADMIN_URL (default postgresql+psycopg://postgres@127.0.0.1:5432/postgres);
each session creates and migrates a throw-away database.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

os.environ.setdefault("NTK_ENV", "test")
os.environ.setdefault("NTK_MODEL_PROVIDER", "mock")
os.environ.setdefault("NTK_EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("NTK_EMBEDDING_DIM", os.environ.get("NTK_TEST_EMBEDDING_DIM", "768"))


def _admin_url() -> str:
    return os.environ.get("NTK_TEST_ADMIN_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/postgres")


@pytest.fixture(scope="session")
def fixture_pdf() -> bytes:
    p = FIXTURES / "synthetic_protocol.pdf"
    if not p.exists():
        import subprocess
        import sys

        subprocess.check_call([sys.executable, str(ROOT / "tools" / "make_fixture_protocol.py"), str(p)])
    return p.read_bytes()


@pytest.fixture(scope="session")
def database_url():
    from sqlalchemy import create_engine, text

    admin = _admin_url()
    try:
        eng = create_engine(admin, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available at {admin}: {exc}")
    name = f"ntk_test_{uuid.uuid4().hex[:10]}"
    with eng.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    url = admin.rsplit("/", 1)[0] + "/" + name
    os.environ["DATABASE_URL"] = url
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "db" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "db" / "alembic"))
    command.upgrade(cfg, "head")
    yield url
    from ntk_common.db import core

    for e in list(core._ENGINES.values()):
        e.dispose()
    core._ENGINES.clear()
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def settings(database_url, tmp_path_factory):
    from ntk_common.config import load_settings

    env = dict(os.environ)
    env.update({
        "DATABASE_URL": database_url,
        "NTK_STORAGE_BACKEND": "local",
        "NTK_LOCAL_STORAGE_DIR": str(tmp_path_factory.mktemp("storage")),
        "NTK_PUBLIC_BASE_URL": "https://api.test.example",
        "NTK_SERVICE_KEYS": '{"wp-test": {"secret": "test-secret-0123456789", "scopes": ["admin:all"]},'
                            ' "reader": {"secret": "reader-secret-0123456789", "scopes": ["admin:read"]}}',
        "NTK_RATE_LIMIT_ASK_PER_MINUTE": "1000",
        "NTK_RATE_LIMIT_SEARCH_PER_MINUTE": "1000",
        "NTK_RATE_LIMIT_PUBLIC_PER_MINUTE": "5000",
    })
    return load_settings(env)


@pytest.fixture(scope="session")
def services(settings):
    from ntk_common.db.core import get_engine
    from ntk_common.orchestrator import build_services

    return build_services(settings, get_engine(settings.database_url))


@pytest.fixture(scope="session")
def pipeline(services):
    from ntk_common.orchestrator import Pipeline

    return Pipeline(services)


@pytest.fixture(scope="session")
def fixture_path(fixture_pdf) -> str:
    return str(FIXTURES / "synthetic_protocol.pdf")


def make_job(services, path: str, *, key: str | None = None, hearing_date: str = "2021-04-12", claim_ids=None):
    from ntk_common.db import ops
    from ntk_common.orchestrator import doc_input_from_manifest, job_idempotency_key

    inp = doc_input_from_manifest({"name": "test", "case_id": services.settings.case_id, "court_record_status": "filed"},
                                  {"local_path": path, "hearing_date": hearing_date, "title": "SYNTHETIC fixture",
                                   "claim_ids": claim_ids or []})
    with services.engine.begin() as conn:
        job, _ = ops.create_job(conn, idempotency_key=key or job_idempotency_key(inp), input_=inp, requested_by="pytest")
    return str(job["id"])


@pytest.fixture(scope="session")
def ingested(services, pipeline, fixture_path):
    job_id = make_job(services, fixture_path)
    job = pipeline.run_job(job_id)
    assert job["status"] == "succeeded", job.get("error")
    return job
