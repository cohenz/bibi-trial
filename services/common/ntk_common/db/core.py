"""Engine creation and small SQL helpers (SQLAlchemy 2 Core).

The schema is SQL-first (db/migrations); this package uses Core with
explicit SQL so that enums, ranges, arrays and pgvector types are used
exactly as defined in the migrations.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

_ENGINES: dict[str, Engine] = {}


def normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine(url: str, *, pool_size: int = 5) -> Engine:
    url = normalize_url(url)
    eng = _ENGINES.get(url)
    if eng is None:
        eng = create_engine(url, pool_size=pool_size, max_overflow=5, pool_pre_ping=True, future=True)
        _ENGINES[url] = eng
    return eng


@contextmanager
def tx(engine: Engine) -> Iterator[Connection]:
    with engine.begin() as conn:
        yield conn


def j(value: Any) -> str:
    """JSON-encode for jsonb parameters."""
    return json.dumps(value, ensure_ascii=False, default=_default)


def _default(o: Any) -> Any:
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if hasattr(o, "hex") and o.__class__.__name__ == "UUID":
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def rows(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    return [dict(r._mapping) for r in conn.execute(text(sql), dict(params or {}))]


def row(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> dict | None:
    r = conn.execute(text(sql), dict(params or {})).first()
    return dict(r._mapping) if r is not None else None


def scalar(conn: Connection, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    return conn.execute(text(sql), dict(params or {})).scalar()


def execute(conn: Connection, sql: str, params: Mapping[str, Any] | list[Mapping[str, Any]] | None = None) -> int:
    if isinstance(params, list):
        if not params:
            return 0
        res = conn.execute(text(sql), params)
    else:
        res = conn.execute(text(sql), dict(params or {}))
    return res.rowcount or 0


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
