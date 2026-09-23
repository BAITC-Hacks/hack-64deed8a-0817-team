"""Guardrails of agent_core/llm_advisor.py, with a fake transport (no network)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import agent_core.llm_advisor as llm_advisor
from agent_core.llm_advisor import MAX_CALLS, TIME_BUDGET_S, LLMAdvisor, TemperatureUnsupported, arm_id

ARMS = [(("tariff_8", "MID"), f"tariff_{i}") for i in range(1, 9)]  # 8 arms, top-6 open to reorder
CAMPAIGNS = [{"campaign_name": "a"}, {"campaign_name": "b"}]


def fake(answer):
    def transport(messages, schema_name, schema):
        if isinstance(answer, Exception):
            raise answer
        return answer
    return transport


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adv = LLMAdvisor()
    assert not adv.enabled
    assert adv.rank_confirmations(ARMS, []) == ARMS
    assert adv.review_finals(CAMPAIGNS, []) == CAMPAIGNS
    assert adv.calls == 0 and adv.log == []


def test_rank_only_reorders_our_top6():
    order = [arm_id(*ARMS[3]), arm_id(("tariff_1", "HIGH"), "tariff_9"), arm_id(*ARMS[7]),
             arm_id(*ARMS[0]), arm_id(*ARMS[3])]
    adv = LLMAdvisor(transport=fake({"order": order, "suspicious": [], "reason": "x"}))
    ranked = adv.rank_confirmations(ARMS, [])
    # outsider and the 7th/8th arm are ignored, nothing dropped, duplicates collapsed
    assert ranked[:2] == [ARMS[3], ARMS[0]]
    assert sorted(ranked[:6]) == sorted(ARMS[:6])
    assert ranked[6:] == ARMS[6:]
    assert adv.log[-1]["status"] == "applied"


def test_review_only_removes_and_never_empties():
    adv = LLMAdvisor(transport=fake({"remove": ["b", "new_campaign"], "reason": "x"}))
    assert adv.review_finals(CAMPAIGNS, []) == [{"campaign_name": "a"}]

    adv = LLMAdvisor(transport=fake({"remove": ["a", "b"], "reason": "x"}))
    assert adv.review_finals(CAMPAIGNS, []) == CAMPAIGNS
    assert adv.log[-1]["status"] == "rejected"


def test_errors_and_call_limit_fall_back():
    adv = LLMAdvisor(transport=fake(TimeoutError("20s")))
    assert adv.rank_confirmations(ARMS, []) == ARMS
    assert adv.log[-1]["status"] == "failed"

    adv = LLMAdvisor(transport=fake({"remove": ["a"], "reason": "x"}))
    for _ in range(MAX_CALLS):
        adv.review_finals(CAMPAIGNS, [])
    assert adv.review_finals(CAMPAIGNS, []) == CAMPAIGNS
    assert adv.calls == MAX_CALLS and adv.log[-1]["status"] == "skipped"


def test_temperature_rejected_once_then_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "stub")
    sent = []

    def stub_post(body):
        sent.append("temperature" in body)
        if "temperature" in body:
            raise TemperatureUnsupported("only default (1) supported")
        return {"remove": [], "reason": "ok"}

    monkeypatch.setattr(llm_advisor, "_post", stub_post)
    adv = LLMAdvisor()
    adv.review_finals(CAMPAIGNS, [])
    adv.review_finals(CAMPAIGNS, [])
    assert sent == [True, False, False]  # one retry, then temperature is no longer sent
    assert adv.calls == 2
    assert [e["status"] for e in adv.log] == ["temperature_default", "applied", "applied"]


def test_time_budget_skips_further_calls():
    now = [0.0]
    transport_calls = []

    def slow_transport(messages, schema_name, schema):
        transport_calls.append(schema_name)
        now[0] += TIME_BUDGET_S / 2 + 1  # each call eats just over half the budget
        return {"remove": [], "reason": "ok"}

    adv = LLMAdvisor(transport=slow_transport, clock=lambda: now[0])
    adv.review_finals(CAMPAIGNS, [])
    adv.review_finals(CAMPAIGNS, [])
    assert adv.review_finals(CAMPAIGNS, []) == CAMPAIGNS  # third call skipped, list untouched
    assert len(transport_calls) == 2 and adv.calls == 2
    assert adv.log[-1]["status"] == "skipped" and "time budget" in adv.log[-1]["reason"]
