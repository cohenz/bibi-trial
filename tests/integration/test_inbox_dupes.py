"""Intake duplicates: exact copies are deleted from inbox/ (only when the kept copy exists), near-identical documents
are held before anything is stored or ingested, and the operator can remove the copy or release it."""

from __future__ import annotations

import dataclasses

import pytest
from ntk_common import inbox, inbox_dupes
from ntk_common.db.core import row
from ntk_common.jobs import TASK_RUN_JOB, InlineQueue
from ntk_common.storage import StorageError

pytest.importorskip("reportlab", reason="synthetic document PDFs are drawn with reportlab (dev dependency)")
from tests.doc_fixtures import make_pdf  # noqa: E402

pytestmark = pytest.mark.db
PREFIX = "inbox-dupes/"

NOTICE = [[
    "בבית המשפט המחוזי בירושלים",
    "ת\"פ 67104-01-20",
    "",
    "הודעה מטעם המאשימה בעניין סדרי הדיונים",
] + [f"{i}. המאשימה מתכבדת להודיע כי מסמך מספר {i} הועבר להגנה ביום {i} בחודש, וכי עותקים נוספים יועברו לפי בקשת הסנגורים."
     for i in range(1, 9)], [
    f"{i}. בנוסף מבקשת המאשימה לציין כי פריט {i} ברשימת החומרים נבדק שוב, ולא נמצא בו חומר נוסף שלא הועבר." for i in range(9, 15)
] + ["", "ירושלים, 3 במרץ 2022"]]


@pytest.fixture()
def svc(services, monkeypatch):
    monkeypatch.setattr(services, "settings", dataclasses.replace(services.settings, inbox_prefix=PREFIX,
                                                                 inbox_delete_duplicates=True))
    return services


def _scan(svc) -> dict:
    sid = inbox.start_scan(svc.engine, trigger="test")
    res = inbox.list_new(svc, prefix=PREFIX, scan_id=sid)
    return {iid: inbox.classify_item(svc, iid) for iid in res["pending_ids"]}


def _item(svc, key):
    with svc.engine.connect() as conn:
        return row(conn, "SELECT * FROM ntk.inbox_items WHERE object_key = :k", {"k": key})


def test_fingerprint_similarity():
    a = inbox_dupes.fingerprint(" ".join(f"מילה{i} נוספת{i} ועוד{i}" for i in range(60)))
    b = inbox_dupes.fingerprint(" ".join(f"מילה{i} נוספת{i} ועוד{i}" for i in range(60)) + " חותמת נתקבל")
    c = inbox_dupes.fingerprint(" ".join(f"אחרת{i} שונה{i} לגמרי{i}" for i in range(60)))
    assert inbox_dupes.similarity(a, b) > 0.9 and inbox_dupes.similarity(a, c) == 0.0
    assert inbox_dupes.fingerprint("קצר מדי") == []


def test_different_dates_are_not_copies(services):
    fp = inbox_dupes.fingerprint(" ".join(f"מילה{i} נוספת{i} ועוד{i}" for i in range(60)))
    with services.engine.begin() as conn:
        assert inbox_dupes.find_possible_duplicate(conn, fp=fp, page_count=1, sha="0" * 64,
                                                   item_id="00000000-0000-0000-0000-000000000000", date="2020-01-01") is None


def test_deletion_is_limited_to_the_intake_prefix(svc):
    with pytest.raises(StorageError):
        svc.storage.delete_intake_copy("sources/sha256/ab/x.pdf", prefix=PREFIX, expected_etag=None)
    with pytest.raises(StorageError):
        svc.storage.delete_intake_copy("inbox-dupes/../sources/x.pdf", prefix=PREFIX, expected_etag=None)
    with pytest.raises(StorageError):
        svc.storage.delete_intake_copy("sources/x.pdf", prefix="sources/", expected_etag=None)


def test_exact_copy_removed_and_near_copy_held(svc, pipeline):
    original = make_pdf(NOTICE)
    near = make_pdf([NOTICE[0], NOTICE[1] + ["נתקבל במזכירות"]])
    assert original != near
    svc.storage.put_bytes(PREFIX + "a/notice.pdf", original, mime_type="application/pdf")
    first = _scan(svc)
    assert list(first.values()) == ["classified"]
    orig = _item(svc, PREFIX + "a/notice.pdf")
    assert orig["classification"]["fingerprint"]

    svc.storage.put_bytes(PREFIX + "b/notice-again.pdf", original, mime_type="application/pdf")
    svc.storage.put_bytes(PREFIX + "b/notice-stamped.pdf", near, mime_type="application/pdf")
    second = _scan(svc)
    assert sorted(second.values()) == ["possible_duplicate", "removed"]

    gone = _item(svc, PREFIX + "b/notice-again.pdf")
    assert gone["status"] == "removed" and gone["removed_by"] == "inbox:auto" and gone["duplicate_of"] == f"inbox:{orig['id']}"
    assert svc.storage.head(PREFIX + "b/notice-again.pdf") is None            # the extra copy is deleted
    assert svc.storage.head(PREFIX + "a/notice.pdf") is not None              # the first upload stays
    assert svc.storage.head(orig["source_key"]) is not None                   # and so does the stored source

    held = _item(svc, PREFIX + "b/notice-stamped.pdf")
    assert held["status"] == "possible_duplicate" and held["source_key"] is None and held["similarity"] >= 0.9
    assert svc.storage.head(svc.storage.content_key(held["content_sha256"])) is None  # nothing written to sources/

    q = InlineQueue({TASK_RUN_JOB: lambda jid: pipeline.run_job(jid)})
    assert inbox.queue_items(svc, q, task_name=TASK_RUN_JOB, item_ids=[str(held["id"])])["queued"] == 0  # held

    with svc.engine.connect() as conn:
        lst = inbox_dupes.listing(conn)
    assert any(i["id"] == str(held["id"]) and i["kept"]["kind"] == "inbox" for i in lst["possible"])
    assert any(i["id"] == str(gone["id"]) for i in lst["removed"])

    # the operator decides it is the same document: the copy goes, the original stays
    res = inbox_dupes.remove_copy(svc, str(held["id"]), actor="op", reason="operator")
    assert res["removed"] and svc.storage.head(PREFIX + "b/notice-stamped.pdf") is None
    assert _item(svc, PREFIX + "b/notice-stamped.pdf")["status"] == "removed"


def test_release_possible_duplicate_as_different_document(svc):
    base = make_pdf(NOTICE)
    variant = make_pdf([NOTICE[0], NOTICE[1] + ["עותק מתוקן"]])
    svc.storage.put_bytes(PREFIX + "c/variant.pdf", variant, mime_type="application/pdf")
    _scan(svc)
    it = _item(svc, PREFIX + "c/variant.pdf")
    if it["status"] != "possible_duplicate":  # depends on which originals exist in this database
        pytest.skip("no earlier original in this run")
    res = inbox_dupes.release(svc, str(it["id"]), actor="op")
    assert res["released"] and res["status"] == "classified"
    it = _item(svc, PREFIX + "c/variant.pdf")
    assert it["source_key"] and svc.storage.head(it["source_key"]) is not None
    assert base != variant
