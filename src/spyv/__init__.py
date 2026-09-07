from __future__ import annotations

from . import terminal
from .checkers import add_allowlist, register_pattern, run_checkers
from .contracts import (
    AttackCase,
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
    RedTeamReport,
    RedTeamResult,
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
from .hooks import GuardBreach, guard, watch
from .probe import probe
from .providers import auto, provider
from .reason import LLMClient, analyze, format_summary
from .redteam import redteam
from .scan import scan

try:  # read from installed metadata so it cannot drift from pyproject.toml
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("spyv")
except (ImportError, PackageNotFoundError):  # pragma: no cover - source checkout
    __version__ = "0.5.0"

__author__ = "Majidul Islam"
__license__ = "Apache-2.0"

__all__ = [
    "AttackCase",
    "AttackEvent",
    "AttackPart",
    "AttackSurface",
    "AttackTurn",
    "Authorization",
    "DiscoveredPrompt",
    "FilePart",
    "Finding",
    "GuardBreach",
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
    "RedTeamReport",
    "RedTeamResult",
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
    "add_allowlist",
    "analyze",
    "auto",
    "discover",
    "format_summary",
    "guard",
    "probe",
    "provider",
    "redteam",
    "register_pattern",
    "run_checkers",
    "scan",
    "terminal",
    "watch",
]
