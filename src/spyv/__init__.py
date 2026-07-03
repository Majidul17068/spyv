from __future__ import annotations

from . import terminal
from .contracts import (
    AttackEvent,
    AttackPart,
    AttackSurface,
    AttackTurn,
    Authorization,
    DiscoveredPrompt,
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
    ProjectPromptResult,
    ProjectReport,
    PromptFix,
    QualityReport,
    QueryProbeReport,
    QueryProbeResult,
    Report,
    Session,
    Severity,
    SpyvFinding,
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

__version__ = "0.1.0"
__author__ = "Majidul Islam"
__license__ = "Apache-2.0"

__all__ = [
    "AttackEvent",
    "AttackPart",
    "AttackSurface",
    "AttackTurn",
    "Authorization",
    "DiscoveredPrompt",
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
    "ProjectPromptResult",
    "ProjectReport",
    "PromptFix",
    "QualityReport",
    "QueryProbeReport",
    "QueryProbeResult",
    "Report",
    "Session",
    "Severity",
    "SpyvFinding",
    "TargetContext",
    "TargetReply",
    "TextPart",
    "ToolArgumentsPart",
    "Vulnerability",
    "__author__",
    "__license__",
    "__version__",
    "analyze",
    "auto",
    "discover",
    "format_summary",
    "probe",
    "provider",
    "scan",
    "terminal",
    "watch",
]
