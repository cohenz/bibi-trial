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


def test_archive_name_wins_and_copies_follow_the_decision(svc, pipeline):
    """Pairs like '0051_1.pdf' + '0051 — 2026-06-30 — החלטה — תיאור.pdf' (same bytes): whichever copy is kept, the stored
    document takes its title and date from the archive name."""
    from ntk_common.db.core import scalar

    body = [[ln.replace("12 באוקטובר", "19 באוקטובר") for ln in NOTICE[0]] + ["16. פסקה ייחודית למסמך הזה בלבד."], NOTICE[1]]
    data = make_pdf(body)
    svc.storage.put_bytes(PREFIX + "d/0051_1.pdf", data, mime_type="application/pdf")
    _scan(svc)
    q = InlineQueue({TASK_RUN_JOB: lambda jid: pipeline.run_job(jid)})
    first = _item(svc, PREFIX + "d/0051_1.pdf")
    if first["status"] != "classified":
        pytest.skip(f"first copy is {first['status']} in this database")
    inbox.queue_items(svc, q, task_name=TASK_RUN_JOB, item_ids=[str(first["id"])])
    with svc.engine.begin() as conn:
        inbox.sync_job_status(conn, str(_item(svc, PREFIX + "d/0051_1.pdf")["job_id"]), "succeeded")
    named = PREFIX + "d/0051 — 2026-06-30 — הודעה — המאשימה מעדכנת על העברת חומרים.pdf"
    svc.storage.put_bytes(named, data, mime_type="application/pdf")
    _scan(svc)
    assert _item(svc, named)["status"] == "removed"
    with svc.engine.connect() as conn:
        d = row(conn, """SELECT d.canonical_title, sv.metadata FROM ntk.source_versions sv
                         JOIN ntk.source_documents d ON d.id = sv.document_id WHERE sv.content_sha256 = :s""",
                {"s": first["content_sha256"]})
        assert d["canonical_title"] == "הודעה: המאשימה מעדכנת על העברת חומרים"
        assert d["metadata"]["document_date"] == "2026-06-30" and d["metadata"]["archive_number"] == "0051"
        assert d["metadata"]["name_from"] == named
        assert inbox_dupes.refresh_names(conn)["retitled"] == 0  # idempotent
        assert scalar(conn, "SELECT count(*) FROM ntk.inbox_items WHERE content_sha256 = :s", {"s": first["content_sha256"]}) == 2


def test_copy_of_a_held_item_follows_its_decision(svc):
    near = make_pdf([NOTICE[0], NOTICE[1] + ["חותמת שנייה"]])
    svc.storage.put_bytes(PREFIX + "e/held.pdf", near, mime_type="application/pdf")
    svc.storage.put_bytes(PREFIX + "e/held-again.pdf", near, mime_type="application/pdf")
    _scan(svc)
    a, b = _item(svc, PREFIX + "e/held.pdf"), _item(svc, PREFIX + "e/held-again.pdf")
    held, copy = (a, b) if a["status"] == "possible_duplicate" else (b, a)
    if held["status"] != "possible_duplicate":
        pytest.skip("no original to be near")
    # an identical copy of a held item is removed at once: one copy is enough to decide on
    assert copy["status"] == "removed" and svc.storage.head(copy["object_key"]) is None
    res = inbox_dupes.remove_copy(svc, str(held["id"]), actor="op", reason="operator")
    assert res["removed"] and svc.storage.head(held["object_key"]) is None


def test_copy_left_behind_follows_the_held_items_removal(svc):
    """A copy recorded as 'duplicate' of a held item (auto-delete off at the time) is removed with it."""
    near = make_pdf([NOTICE[0], NOTICE[1] + ["חותמת שלישית"]])
    off = dataclasses.replace(svc.settings, inbox_delete_duplicates=False)
    svc.settings, on = off, svc.settings
    try:
        svc.storage.put_bytes(PREFIX + "f/held.pdf", near, mime_type="application/pdf")
        svc.storage.put_bytes(PREFIX + "f/held-again.pdf", near, mime_type="application/pdf")
        _scan(svc)
    finally:
        svc.settings = on
    a, b = _item(svc, PREFIX + "f/held.pdf"), _item(svc, PREFIX + "f/held-again.pdf")
    held, copy = (a, b) if a["status"] == "possible_duplicate" else (b, a)
    if held["status"] != "possible_duplicate":
        pytest.skip("no original to be near")
    assert copy["status"] == "duplicate"
    res = inbox_dupes.remove_copy(svc, str(held["id"]), actor="op", reason="operator")
    assert res["removed"] and res["copies_removed"] == [str(copy["id"])]
    assert svc.storage.head(copy["object_key"]) is None and svc.storage.head(held["object_key"]) is None


def test_resaved_copy_with_same_text_and_pages_is_removed(svc):
    """Operator rule: no substantive difference → not processed twice. Same text and page count, other bytes."""
    body = [[ln.replace("12 באוקטובר", "17 באוקטובר") for ln in NOTICE[0]] + ["17. פסקה שמבדילה את המסמך הזה."], NOTICE[1]]
    resaved = [["", *body[0]], body[1]]  # a blank line moves the text: different bytes, same text
    a, b = make_pdf(body), make_pdf(resaved)
    assert a != b
    svc.storage.put_bytes(PREFIX + "g/original.pdf", a, mime_type="application/pdf")
    _scan(svc)
    if _item(svc, PREFIX + "g/original.pdf")["status"] != "classified":
        pytest.skip("original not classified in this database")
    svc.storage.put_bytes(PREFIX + "g/resaved.pdf", b, mime_type="application/pdf")
    _scan(svc)
    it = _item(svc, PREFIX + "g/resaved.pdf")
    assert it["status"] == "removed" and "near-identical" in it["error"]["removed_reason"]
    assert svc.storage.head(PREFIX + "g/resaved.pdf") is None
