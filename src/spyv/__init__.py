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
    DiscoveredPrompt,
    ProjectPromptResult,
    ProjectReport,
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
from .discovery import discover
from .hooks import watch
from .probe import probe
from .providers import auto, provider
from .reason import LLMClient, analyze, format_summary
from .scan import scan

__version__ = "0.0.3a3"
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
    "discover",
    "format_summary",
    "probe",
    "provider",
    "scan",
    "terminal",
    "watch",
    "QueryProbeReport",
    "QueryProbeResult",
    "DiscoveredPrompt",
    "ProjectReport",
    "ProjectPromptResult",
]
