"""Every adversarial golden question must be caught by a deterministic
pre-model detector; ordinary questions must not be."""

import json
from pathlib import Path

import pytest
from ntk_common.ask import detect_injection, detect_outcome_premises, detect_ruling_attribution, detect_speaker_claim

SUITE = json.loads((Path(__file__).resolve().parents[2] / "golden" / "adversarial-v1.json").read_text(encoding="utf-8"))


def detected(q: str) -> bool:
    return bool(detect_outcome_premises(q) or detect_injection(q) or detect_ruling_attribution(q) or detect_speaker_claim(q))


@pytest.mark.parametrize("item", SUITE["questions"], ids=lambda i: i["id"])
def test_adversarial_question_is_detected(item):
    assert detected(item["question"]), item["question"]


def test_suite_has_at_least_50_questions_and_20_false_premises():
    assert len(SUITE["questions"]) >= 50
    assert sum(1 for q in SUITE["questions"] if q["category"] == "false_premise") >= 20


@pytest.mark.parametrize("q", [
    "מה אמרו השופטים על עבירת השוחד?", "מה קרה עם בקשת החנינה?", "מתי יינתן פסק הדין?", "מה אמר העד על הפגישה?",
    "מי שלח את המיילים?", "האם העד קיבל הנחיות ישירות?", "מה העונש המקסימלי על שוחד לפי החוק?", "מה טענה ההגנה לגבי הנחיות?",
    "מה עשה העד לפני פסק הדין?", "איך נבחר ההרכב?",
])
def test_ordinary_questions_are_not_flagged(q):
    assert not (detect_outcome_premises(q) or detect_injection(q) or detect_ruling_attribution(q))
