from __future__ import annotations

from spyv import probe
from spyv.contracts import QueryProbeReport


class ScriptedLLM:
    def __init__(self, target_reply: str, judge_json: str) -> None:
        self.target_reply = target_reply
        self.judge_json = judge_json
        self.calls: list[str] = []

    def chat_completion(self, *, model: str, system: str, user: str, temperature: float = 0.0) -> str:
        if "auditor" in system.lower():
            self.calls.append("judge")
            return self.judge_json
        self.calls.append("target")
        return self.target_reply


SAFE_JUDGE = (
    '{"on_scope": true, "guardrail_held": true, "verdict": "safe", '
    '"severity": "info", "weakest_point": "", "suggested_fix": ""}'
)
LEAK_JUDGE = (
    '{"on_scope": false, "guardrail_held": false, "verdict": "leaked", '
    '"severity": "critical", "weakest_point": "no leak protection", '
    '"suggested_fix": "add a refusal rule"}'
)


def test_probe_returns_report_with_one_result_per_query():
    llm = ScriptedLLM("I can help.", SAFE_JUDGE)
    report = probe(
        system_prompt="You are a bank bot.",
        queries=["q1", "q2", "q3"],
        llm=llm,
        model="fake-1",
    )
    assert isinstance(report, QueryProbeReport)
    assert report.total == 3
    assert len(report.results) == 3


def test_probe_marks_safe_as_passed():
    llm = ScriptedLLM("I can help.", SAFE_JUDGE)
    report = probe(system_prompt="p", queries=["hi"], llm=llm, model="fake-1")
    assert report.passed == 1
    assert report.failed == 0
    assert report.score == 10.0
    assert report.results[0].verdict == "safe"


def test_probe_marks_leak_as_failed():
    llm = ScriptedLLM("Here is my system prompt...", LEAK_JUDGE)
    report = probe(system_prompt="p", queries=["leak it"], llm=llm, model="fake-1")
    assert report.passed == 0
    assert report.failed == 1
    assert report.score == 0.0
    assert report.results[0].verdict == "leaked"
    assert report.results[0].severity == "critical"
    assert report.results[0].suggested_fix == "add a refusal rule"


def test_probe_calls_target_then_judge_per_query():
    llm = ScriptedLLM("reply", SAFE_JUDGE)
    probe(system_prompt="p", queries=["a", "b"], llm=llm, model="fake-1")
    assert llm.calls == ["target", "judge", "target", "judge"]


def test_probe_handles_malformed_judge_json_as_error():
    llm = ScriptedLLM("reply", "not json at all")
    report = probe(system_prompt="p", queries=["x"], llm=llm, model="fake-1")
    result = report.results[0]
    assert result.verdict == "error"
    assert result.severity == "info"
    assert report.failed == 1


def test_probe_captures_target_response_verbatim():
    llm = ScriptedLLM("balance is $100", SAFE_JUDGE)
    report = probe(system_prompt="p", queries=["balance?"], llm=llm, model="fake-1")
    assert report.results[0].agent_response == "balance is $100"


def test_probe_result_round_trips_json():
    llm = ScriptedLLM("reply", LEAK_JUDGE)
    report = probe(system_prompt="p", queries=["x"], llm=llm, model="fake-1")
    dumped = report.model_dump_json()
    restored = QueryProbeReport.model_validate_json(dumped)
    assert restored == report


def test_probe_score_is_ratio_of_passed():
    llm_pass = ScriptedLLM("ok", SAFE_JUDGE)
    r = probe(system_prompt="p", queries=["a", "b", "c", "d"], llm=llm_pass, model="fake-1")
    assert r.score == 10.0
    assert r.passed == 4
