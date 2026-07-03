from __future__ import annotations

import ast
import json
from pathlib import Path

from .contracts import DiscoveredPrompt

_NAME_HINTS = (
    "system_prompt",
    "system_message",
    "sys_prompt",
    "system",
    "instructions",
    "persona",
    "prompt",
    "preamble",
    "role_prompt",
)
_YAML_KEYS = ("system_prompt", "system", "persona", "instructions", "prompt", "preamble")
_MIN_LEN = 40
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".idea",
    ".tox",
    "site-packages",
    ".egg-info",
}


def _name_matches(name: str) -> bool:
    low = name.lower()
    return any(hint in low for hint in _NAME_HINTS)


_PROMPT_CUES = (
    "you are", "your role", "your task", "your job", "you must", "you should",
    "you will", "you can", "act as", "respond", "reply", "return ", "analyse",
    "analyze", "generate", "classify", "summarize", "summarise", "extract",
    "translate", "role:", "goal:", "backstory:", "system:", "instruction",
    "assistant", "do not", "must not", "guideline", "rules", "context:",
    "persona", "format:", "your goal", "you help",
)

_SYSTEM_MESSAGE_CALLS = {"SystemMessage", "SystemMessagePromptTemplate"}


def _looks_like_prompt(text: str) -> bool:
    t = text.strip()
    if len(t) < _MIN_LEN:
        return False
    if len(t) >= 200:
        return True
    low = t.lower()
    return any(cue in low for cue in _PROMPT_CUES)


def _call_name(func: ast.expr) -> str | None:
    return getattr(func, "id", None) or getattr(func, "attr", None)


def _first_string_arg(node: ast.Call) -> str | None:
    for a in node.args:
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def _crewai_prompt(kw_strings: dict[str, str]) -> str | None:
    if "role" not in kw_strings:
        return None
    if "goal" not in kw_strings and "backstory" not in kw_strings:
        return None
    parts = []
    if kw_strings.get("role"):
        parts.append(f"ROLE: {kw_strings['role']}")
    if kw_strings.get("goal"):
        parts.append(f"GOAL: {kw_strings['goal']}")
    if kw_strings.get("backstory"):
        parts.append(f"BACKSTORY: {kw_strings['backstory']}")
    combined = "\n".join(parts)
    return combined if len(combined) >= _MIN_LEN else None


def _langchain_prompt(node: ast.Call, kw_strings: dict[str, str]) -> tuple[str, str] | None:
    name = _call_name(node.func)
    if name in _SYSTEM_MESSAGE_CALLS:
        text = _first_string_arg(node) or kw_strings.get("content")
        if text and len(text) >= _MIN_LEN:
            return name, text
    if name == "from_template":
        text = _first_string_arg(node) or kw_strings.get("template")
        if text and len(text) >= _MIN_LEN:
            return "from_template", text
    if name and name.endswith("PromptTemplate"):
        text = kw_strings.get("template") or _first_string_arg(node)
        if text and len(text) >= _MIN_LEN:
            return name, text
    return None


def _from_python(path: Path, text: str) -> list[DiscoveredPrompt]:
    found: list[DiscoveredPrompt] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            if len(value.value) < _MIN_LEN:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                name = getattr(t, "id", None) or getattr(t, "attr", None)
                if name and _name_matches(name):
                    found.append(
                        DiscoveredPrompt(
                            file=str(path),
                            line=node.lineno,
                            source_kind="python_var",
                            identifier=name,
                            system_prompt=value.value,
                        )
                    )
                    break

        if isinstance(node, ast.Call):
            kw_strings: dict[str, str] = {}
            for kw in node.keywords:
                if kw.arg and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    kw_strings[kw.arg] = kw.value.value

            crew_prompt = _crewai_prompt(kw_strings)
            lc = _langchain_prompt(node, kw_strings)
            if crew_prompt is not None:
                found.append(
                    DiscoveredPrompt(
                        file=str(path),
                        line=node.lineno,
                        source_kind="crewai_agent",
                        identifier=kw_strings["role"][:60],
                        system_prompt=crew_prompt,
                    )
                )
            elif lc is not None:
                found.append(
                    DiscoveredPrompt(
                        file=str(path),
                        line=node.lineno,
                        source_kind="langchain",
                        identifier=lc[0],
                        system_prompt=lc[1],
                    )
                )
            else:
                for kw in node.keywords:
                    if not kw.arg or not _name_matches(kw.arg):
                        continue
                    v = kw.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) and len(v.value) >= _MIN_LEN:
                        found.append(
                            DiscoveredPrompt(
                                file=str(path),
                                line=getattr(v, "lineno", node.lineno),
                                source_kind="python_var",
                                identifier=kw.arg,
                                system_prompt=v.value,
                            )
                        )

        if isinstance(node, ast.Tuple) and len(node.elts) >= 2:
            first, second = node.elts[0], node.elts[1]
            if (
                isinstance(first, ast.Constant)
                and first.value == "system"
                and isinstance(second, ast.Constant)
                and isinstance(second.value, str)
                and len(second.value) >= _MIN_LEN
            ):
                found.append(
                    DiscoveredPrompt(
                        file=str(path),
                        line=getattr(second, "lineno", node.lineno),
                        source_kind="langchain",
                        identifier="system tuple",
                        system_prompt=second.value,
                    )
                )

        if isinstance(node, ast.Dict):
            role_is_system = False
            content_value: str | None = None
            content_line: int | None = None
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "role":
                    if isinstance(v, ast.Constant) and v.value == "system":
                        role_is_system = True
                if isinstance(k, ast.Constant) and k.value == "content":
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        content_value = v.value
                        content_line = getattr(v, "lineno", node.lineno)
            if role_is_system and content_value and len(content_value) >= _MIN_LEN:
                found.append(
                    DiscoveredPrompt(
                        file=str(path),
                        line=content_line,
                        source_kind="openai_message",
                        identifier="system message",
                        system_prompt=content_value,
                    )
                )
    return found


def _tools_from_mapping(data: dict) -> list[str]:
    raw = data.get("tools")
    tools: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                tools.append(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                tools.append(item["name"])
    return tools


def _from_mapping(path: Path, data: object, source_kind: str) -> list[DiscoveredPrompt]:
    found: list[DiscoveredPrompt] = []
    if isinstance(data, dict):
        for key in _YAML_KEYS:
            val = data.get(key)
            if isinstance(val, str) and len(val) >= _MIN_LEN:
                found.append(
                    DiscoveredPrompt(
                        file=str(path),
                        source_kind=source_kind,  # type: ignore[arg-type]
                        identifier=key,
                        system_prompt=val,
                        tools=_tools_from_mapping(data),
                    )
                )
        for val in data.values():
            found.extend(_from_mapping(path, val, source_kind))
    elif isinstance(data, list):
        for item in data:
            found.extend(_from_mapping(path, item, source_kind))
    return found


def _from_yaml(path: Path, text: str) -> list[DiscoveredPrompt]:
    try:
        import yaml
    except ImportError:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    return _from_mapping(path, data, "yaml")


def _from_json(path: Path, text: str) -> list[DiscoveredPrompt]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return _from_mapping(path, data, "json")


def _from_prompt_file(path: Path, text: str) -> list[DiscoveredPrompt]:
    if len(text.strip()) < _MIN_LEN:
        return []
    return [
        DiscoveredPrompt(
            file=str(path),
            source_kind="prompt_file",
            identifier=path.name,
            system_prompt=text.strip(),
        )
    ]


def _is_prompt_file(path: Path) -> bool:
    if path.suffix.lower() not in (".txt", ".md"):
        return False
    parts = {p.lower() for p in path.parts}
    return "prompts" in parts or "prompt" in path.stem.lower()


def _dedupe(prompts: list[DiscoveredPrompt]) -> list[DiscoveredPrompt]:
    seen: set[tuple[str, str]] = set()
    out: list[DiscoveredPrompt] = []
    for p in prompts:
        key = (p.file, p.system_prompt)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def discover(root: str | Path) -> tuple[list[DiscoveredPrompt], int]:
    root_path = Path(root)
    prompts: list[DiscoveredPrompt] = []
    files_scanned = 0

    if root_path.is_file():
        candidates = [root_path]
    else:
        candidates = []
        for p in root_path.rglob("*"):
            if p.is_dir():
                continue
            if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in p.parts):
                continue
            candidates.append(p)

    for path in candidates:
        suffix = path.suffix.lower()
        try:
            if suffix == ".py":
                text = path.read_text(encoding="utf-8")
                files_scanned += 1
                prompts.extend(_from_python(path, text))
            elif suffix in (".yaml", ".yml"):
                text = path.read_text(encoding="utf-8")
                files_scanned += 1
                prompts.extend(_from_yaml(path, text))
            elif suffix == ".json":
                text = path.read_text(encoding="utf-8")
                files_scanned += 1
                prompts.extend(_from_json(path, text))
            elif _is_prompt_file(path):
                text = path.read_text(encoding="utf-8")
                files_scanned += 1
                prompts.extend(_from_prompt_file(path, text))
        except (OSError, UnicodeDecodeError):
            continue

    filtered = [p for p in prompts if _looks_like_prompt(p.system_prompt)]
    return _dedupe(filtered), files_scanned


__all__ = ["discover"]
