import json
import subprocess
import sys
from pathlib import Path

import pytest

from ntk_common import contracts, hebrew, ids

ROOT = Path(__file__).resolve().parents[2]


def test_stable_id_shape_and_determinism():
    a = ids.stable_id("su", ["sv_x", 1, 1, 2, 0, 'עו"ד חדד'])
    assert a == ids.stable_id("su", ["sv_x", 1, 1, 2, 0, 'עו"ד חדד'])
    assert a.startswith("su_") and len(a) == 29
    assert a != ids.stable_id("su", ["sv_x", 1, 1, 3, 0, 'עו"ד חדד'])


def test_known_vector_matches_sql_function():
    # same value is asserted against ntk.stable_id() in tests/integration/test_db_pipeline.py
    assert ids.stable_id("su", ["sv_x", 1, 1, 2, 0, 'עו"ד חדד']) == "su_b2543bbf2fc89197c12455c502"


def test_speaker_label_normalisation_is_cosmetic_only():
    assert ids.normalize_speaker_label("עו״ד חדד:") == ids.normalize_speaker_label('עו"ד  חדד')
    assert ids.normalize_speaker_label("עו״ד חדד") != ids.normalize_speaker_label("עו״ד חן")


def test_unit_id_does_not_depend_on_text():
    u1 = ids.source_unit_id("sv_a", 3, 4, 7, 12, "העד")
    u2 = ids.source_unit_id("sv_a", 3, 4, 7, 12, "העד")
    assert u1 == u2


def test_derived_uuid_is_v5_and_stable():
    u = ids.derived_uuid("claim", "case", "slug")
    assert u.version == 5 and u == ids.derived_uuid("claim", "case", "slug")


@pytest.mark.parametrize("raw,expected", [
    ('עו"ד', "עו״ד"), ("כב'", "כב׳"), ("אלוביץ'", "אלוביץ׳"), ("שָׁלוֹם", "שלום"), ("a‏b", "ab"),
])
def test_normalize(raw, expected):
    assert hebrew.normalize(raw) == expected


def test_normalize_keeps_identifiers():
    t = hebrew.normalize("ת״פ 67104-01-20 מיום 5.4.2021 מוצג ת/123")
    assert "67104-01-20" in t and "5.4.2021" in t and "ת/123" in t


def test_prefix_forms():
    assert "הלכתי" in hebrew.prefix_forms("וכשהלכתי")
    assert "משפט" in hebrew.prefix_forms("המשפט")
    assert hebrew.prefix_forms("בית") == []  # no 2-letter stems


def test_search_terms_expand_abbreviations():
    terms = hebrew.search_terms('עו"ד חדד')
    assert "עורכ" in terms and "דינ" in terms  # folded final letters


def test_visual_order_repair():
    logical = "הוא פסק דין של בית המשפט 2021"
    visual = hebrew.reverse_visual_line(logical)
    fixed, flipped = hebrew.fix_visual_order([visual])
    assert flipped and fixed[0] == logical


def test_contracts_file_is_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_contracts.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_all_brief_objects_have_contracts():
    names = set(contracts.contract_names())
    for n in ["Document", "SourceVersion", "SourceUnit", "ExchangeUnit", "RetrievalChunk", "Hearing", "HearingDigest", "Person",
              "Claim", "ClaimBundle", "Evidence", "Citation", "Project315Event", "Artifact", "ArtifactVersion", "ReviewTask",
              "Publication", "AnswerEnvelope", "IngestionJob", "AuditEvent", "ModelRun", "ModelRegistryEntry"]:
        assert n in names, n


def test_contract_rejects_bad_citation():
    bad = {"source_unit_id": "su_123", "source_version_id": "sv_" + "0" * 26, "page": 0, "line_start": 1, "line_end": 1,
           "permalink": "not a uri"}
    with pytest.raises(contracts.ContractError) as ei:
        contracts.validate("Citation", bad)
    paths = {e["path"] for e in ei.value.errors}
    assert "/source_unit_id" in paths and "/page" in paths and "/permalink" in paths


def test_unknown_major_schema_version_rejected():
    with pytest.raises(contracts.ContractError) as ei:
        contracts.validate("HearingDigest", {"schema_version": "3.0"})
    assert ei.value.errors[0]["validator"] == "unsupported_schema"


def test_openapi_is_valid_json():
    spec = json.loads((ROOT / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    assert "/v2/ask" in spec["paths"] and "ErrorEnvelope" in spec["components"]["schemas"]
