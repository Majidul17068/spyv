from __future__ import annotations

from datetime import datetime, timezone

from .attacks import load_attacks
from .contracts import RedTeamReport, RedTeamResult
from .hybrid import _worst, merge_verdict
from .probe import _judge, _run_target
from .providers.base import LLMClient


def _breached(verdict: str, guardrail_held: bool) -> bool:
    return not (verdict == "safe" and guardrail_held)


def redteam(
    *,
    system_prompt: str,
    llm: LLMClient,
    model: str,
    categories: list[str] | None = None,
    tools: list[str] | None = None,
) -> RedTeamReport:
    from .reason import _target_hash

    attacks = load_attacks(categories)
    results: list[RedTeamResult] = []
    breached = 0

    for attack in attacks:
        response = _run_target(llm, model, system_prompt, attack.payload)
        judged = _judge(llm, model, system_prompt, attack.payload, response)
        merged = merge_verdict(system_prompt, response, judged)
        did_breach = _breached(merged["verdict"], merged["guardrail_held"])
        if did_breach:
            severity = _worst(merged["severity"], attack.severity_if_breached)
            breached += 1
        else:
            severity = "info"
        results.append(
            RedTeamResult(
                attack_id=attack.id,
                category=attack.category,
                name=attack.name,
                payload=attack.payload,
                agent_response=response,
                verdict=merged["verdict"],
                severity=severity,
                breached=did_breach,
                source=merged["source"],
                confidence=merged["confidence"],
                needs_review=merged["needs_review"],
                checker_hits=merged["checker_hits"],
                weakest_point=merged["weakest_point"],
                suggested_fix=merged["suggested_fix"],
            )
        )

    _SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    results.sort(key=lambda r: (not r.breached, -_SEVERITY_RANK.get(r.severity, 0)))

    return RedTeamReport(
        target_hash=_target_hash(system_prompt, tools),
        model_used=model,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total=len(results),
        breached=breached,
        held=len(results) - breached,
        categories_tested=sorted({a.category for a in attacks}),
        results=results,
    )


__all__ = ["redteam"]
