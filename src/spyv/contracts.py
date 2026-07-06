from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]
Pillar = Literal["quality", "optimization", "vulnerability", "guardrail"]
OverallVerdict = Literal["ship", "fix_first", "unsafe"]


class SpyvFinding(BaseModel):
    id: str
    pillar: Pillar
    severity: Severity
    title: str
    description: str
    line: int | None = None
    evidence: str | None = None
    owasp_llm_tag: str | None = None
    fix_id: str | None = None


class PromptFix(BaseModel):
    id: str
    priority: int
    addresses: list[str] = Field(default_factory=list)
    kind: Literal["add", "replace", "remove"]
    insertion_point: str
    original: str | None = None
    replacement: str
    rationale: str


class QualityReport(BaseModel):
    score: float
    findings: list[SpyvFinding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class OptimizationReport(BaseModel):
    score: float
    total_tokens: int
    redundant_tokens: int = 0
    estimated_savings_tokens: int = 0
    estimated_cost_savings_per_1k_calls_usd: float = 0.0
    estimated_latency_reduction_ms: float = 0.0
    findings: list[SpyvFinding] = Field(default_factory=list)


class Vulnerability(BaseModel):
    id: str
    owasp_llm_tag: str | None = None
    mitre_atlas_id: str | None = None
    category: str
    severity: Severity
    status: Literal["predicted", "confirmed", "refuted"] = "predicted"
    prediction_confidence: float = 0.5
    title: str
    description: str
    root_cause: str = ""
    suggested_fix: str = ""


class Guardrail(BaseModel):
    line: int | None = None
    text: str
    kind: str
    strength: Literal["weak", "medium", "strong"]
    bypass_risk: str = ""


class MissingGuardrail(BaseModel):
    kind: str
    severity: Severity
    suggested_text: str


class GuardrailAudit(BaseModel):
    score: float
    found: list[Guardrail] = Field(default_factory=list)
    missing: list[MissingGuardrail] = Field(default_factory=list)


class Report(BaseModel):
    target_hash: str
    model_used: str
    reason_checksum: str
    generated_at: str
    overall_score: float
    overall_verdict: OverallVerdict
    quality: QualityReport
    optimization: OptimizationReport
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    guardrails: GuardrailAudit
    fixes: list[PromptFix] = Field(default_factory=list)
    attack_run_included: bool = False


ProbeVerdict = Literal["safe", "off_scope", "leaked", "complied_with_attack", "error"]


EvidenceSource = Literal["deterministic", "llm", "both"]


class QueryProbeResult(BaseModel):
    query: str
    agent_response: str
    on_scope: bool
    guardrail_held: bool
    verdict: ProbeVerdict
    severity: Severity
    source: EvidenceSource = "llm"
    confidence: float = 0.6
    needs_review: bool = False
    checker_hits: list[str] = Field(default_factory=list)
    weakest_point: str = ""
    suggested_fix: str = ""


class QueryProbeReport(BaseModel):
    target_hash: str
    model_used: str
    generated_at: str
    score: float
    total: int
    passed: int
    failed: int
    results: list[QueryProbeResult] = Field(default_factory=list)


SourceKind = Literal[
    "yaml", "json", "python_var", "openai_message", "prompt_file", "crewai_agent", "langchain"
]


class DiscoveredPrompt(BaseModel):
    file: str
    line: int | None = None
    source_kind: SourceKind
    identifier: str = ""
    system_prompt: str
    tools: list[str] = Field(default_factory=list)


class ProjectPromptResult(BaseModel):
    file: str
    line: int | None = None
    source_kind: SourceKind
    identifier: str = ""
    overall_score: float
    overall_verdict: OverallVerdict
    n_vulnerabilities: int = 0
    max_severity: Severity = "info"
    top_fix: str = ""


class ProjectReport(BaseModel):
    root: str
    generated_at: str
    model_used: str
    files_scanned: int
    prompts_found: int
    prompts_analyzed: int
    truncated: bool = False
    ship: int = 0
    fix_first: int = 0
    unsafe: int = 0
    results: list[ProjectPromptResult] = Field(default_factory=list)


class AttackCase(BaseModel):
    id: str
    category: str
    name: str
    payload: str
    severity_if_breached: Severity = "high"


class RedTeamResult(BaseModel):
    attack_id: str
    category: str
    name: str
    payload: str
    agent_response: str
    verdict: ProbeVerdict
    severity: Severity
    breached: bool
    source: EvidenceSource = "llm"
    confidence: float = 0.6
    needs_review: bool = False
    checker_hits: list[str] = Field(default_factory=list)
    weakest_point: str = ""
    suggested_fix: str = ""


class RedTeamReport(BaseModel):
    target_hash: str
    model_used: str
    generated_at: str
    total: int
    breached: int
    held: int
    categories_tested: list[str] = Field(default_factory=list)
    results: list[RedTeamResult] = Field(default_factory=list)


class Authorization(BaseModel):
    model_config = {"frozen": True}

    attesting_user: str
    scope: str
    accepted_aup_version: str
    timestamp: str
    written_authorization_ref: str | None = None


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    kind: Literal["image"] = "image"
    mime: str
    data_hash: str


class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    mime: str
    name: str
    data_hash: str


class ToolArgumentsPart(BaseModel):
    kind: Literal["tool_arguments"] = "tool_arguments"
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


AttackPart = TextPart | ImagePart | FilePart | ToolArgumentsPart


class AttackTurn(BaseModel):
    attacker_checksum: str
    attack_id: str
    turn_index: int
    role: Literal["user", "system", "tool"] = "user"
    parts: list[AttackPart] = Field(min_length=1)
    encoding: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TargetReply(BaseModel):
    text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_hits: list[dict[str, Any]] = Field(default_factory=list)
    stream_events: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0
    usage: dict[str, int | float] = Field(default_factory=dict)
    error: str | None = None


class TargetContext(BaseModel):
    target_checksum: str
    target_purpose: str
    target_tools: list[str] = Field(default_factory=list)
    prior_turns: list[AttackTurn] = Field(default_factory=list)
    last_target_reply: TargetReply | None = None
    seed: int


class AttackEvent(BaseModel):
    turn: AttackTurn
    reply: TargetReply
    span_ids: list[str] = Field(default_factory=list)
    timestamp: str


class JudgeVerdict(BaseModel):
    judge_checksum: str
    judge_name: str
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    scanner_hits: dict[str, float] = Field(default_factory=dict)


class Finding(BaseModel):
    id: str
    run_id: str
    target_checksum: str
    attacker_checksum: str
    judge_checksum: str
    seed: int
    vulnerability: Vulnerability
    verdict: JudgeVerdict
    events: list[AttackEvent] = Field(default_factory=list)
    evidence_hash: str
    signature: str
    created_at: str
    embargo_until: str | None = None


class AttackSurface(BaseModel):
    target_checksum: str
    reasoned_by_model: str
    reasoned_by_reason_checksum: str
    role_summary: str
    tools_declared: list[str] = Field(default_factory=list)
    destructive_tools: list[str] = Field(default_factory=list)
    data_at_risk: list[str] = Field(default_factory=list)
    guardrails_found: list[str] = Field(default_factory=list)
    guardrail_weaknesses: list[str] = Field(default_factory=list)
    predicted_vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    reasoning_trace: str = ""


class Session(BaseModel):
    run_id: str
    started_at: str
    authorization: Authorization
    target_checksum: str
    attacker_checksums: list[str] = Field(default_factory=list)
    judge_checksums: list[str] = Field(default_factory=list)
    seed: int
    policy_name: str
    budget_usd: float
    findings: list[Finding] = Field(default_factory=list)
    manifest_signature: str | None = None
