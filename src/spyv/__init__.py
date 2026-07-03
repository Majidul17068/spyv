from __future__ import annotations

from . import terminal
from .contracts import (
    AttackEvent,
    AttackPart,
    AttackSurface,
    AttackTurn,
    Authorization,
    FilePart,
    Finding,
    Guardrail,
    GuardrailAudit,
    ImagePart,
    JudgeVerdict,
    MissingGuardrail,
    OptimizationReport,
    OverallVerdict,
    Pillar,
    PromptFix,
    QualityReport,
    QueryProbeReport,
    QueryProbeResult,
    SpyvFinding,
    Report,
    Session,
    Severity,
    TargetContext,
    TargetReply,
    TextPart,
    ToolArgumentsPart,
    Vulnerability,
)
from .hooks import watch
from .probe import probe
from .providers import auto, provider
from .reason import LLMClient, analyze, format_summary

__version__ = "0.0.2a1"
__author__ = "Majidul Islam"
__license__ = "Apache-2.0"

__all__ = [
    "__author__",
    "__license__",
    "__version__",
    "AttackEvent",
    "AttackPart",
    "AttackSurface",
    "AttackTurn",
    "Authorization",
    "FilePart",
    "Finding",
    "Guardrail",
    "GuardrailAudit",
    "ImagePart",
    "JudgeVerdict",
    "LLMClient",
    "MissingGuardrail",
    "OptimizationReport",
    "OverallVerdict",
    "Pillar",
    "PromptFix",
    "QualityReport",
    "SpyvFinding",
    "Report",
    "Session",
    "Severity",
    "TargetContext",
    "TargetReply",
    "TextPart",
    "ToolArgumentsPart",
    "Vulnerability",
    "analyze",
    "auto",
    "format_summary",
    "probe",
    "provider",
    "terminal",
    "watch",
    "QueryProbeReport",
    "QueryProbeResult",
]
