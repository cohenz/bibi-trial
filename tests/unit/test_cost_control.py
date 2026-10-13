"""Ask cost control (13.10.2026): the writer's thinking level reaches Gemini, a model that refuses the setting is
asked again without it, and the daily budget counts only new answers."""

from __future__ import annotations

import pytest
from ntk_common.ask import AskLimited
from ntk_common.llm.providers import GeminiProvider, ProviderError

OK = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}], "usageMetadata": {"promptTokenCount": 10}}


def _provider(responses):
    p = GeminiProvider("k", "https://example.invalid")
    sent = []

    def post(path, body):
        import copy

        sent.append(copy.deepcopy(body))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    p._post = post
    return p, sent


def test_thinking_level_and_budget_are_sent():
    p, sent = _provider([OK, OK])
    p.generate_json(model_id="m", system="s", user="u", temperature=0, task_type="answer", thinking="low")
    p.generate_json(model_id="m", system="s", user="u", temperature=0, task_type="answer", thinking="512")
    assert sent[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert sent[1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 512}


def test_no_thinking_setting_by_default():
    p, sent = _provider([OK])
    p.generate_json(model_id="m", system="s", user="u", temperature=0, task_type="digest")
    assert "thinkingConfig" not in sent[0]["generationConfig"]


def test_model_that_refuses_the_setting_is_asked_again_without_it():
    err = ProviderError("gemini HTTP 400: Invalid value at 'generation_config.thinking_config.thinking_level'",
                        retryable=False, status=400)
    p, sent = _provider([err, OK])
    p.generate_json(model_id="m", system="s", user="u", temperature=0, task_type="answer", thinking="low")
    assert len(sent) == 2 and "thinkingConfig" not in sent[1]["generationConfig"]


def test_other_400s_are_not_hidden():
    p, _ = _provider([ProviderError("gemini HTTP 400: bad request", retryable=False, status=400)])
    with pytest.raises(ProviderError):
        p.generate_json(model_id="m", system="s", user="u", temperature=0, task_type="answer", thinking="low")


def test_daily_budget():
    pytest.importorskip("fastapi")
    from ntk_api import ask_budget

    ask_budget._MEM.clear()
    b = ask_budget.AskBudget(None, daily_limit=3, visitor_limit=2)
    b.reserve("v1")
    b.reserve("v1")
    with pytest.raises(AskLimited) as e:
        b.reserve("v1")
    assert e.value.reason == "visitor_daily_limit"
    b.reserve("v2")
    with pytest.raises(AskLimited) as e:
        b.reserve("v3")
    assert e.value.reason == "daily_limit"
    assert b.counters(ask_budget._today())["model"] == 3
    ask_budget._MEM.clear()
