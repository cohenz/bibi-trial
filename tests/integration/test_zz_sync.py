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
