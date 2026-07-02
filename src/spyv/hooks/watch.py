from __future__ import annotations

import asyncio
import json as _json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from functools import wraps
from typing import IO, Any, Callable, TypeVar

from rich.text import Text

from ..terminal import _resolve_console

F = TypeVar("F", bound=Callable[..., Any])

_logger = logging.getLogger("spyv.watch")

_STATUS_STYLE: dict[str, str] = {
    "ok": "green",
    "error": "bold red",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_output_mode() -> str:
    env = os.environ.get("SPYV_OUT", "").lower()
    if env in ("pretty", "json", "both"):
        return env
    return "pretty" if sys.stderr.isatty() else "json"


def _emit_pretty(fn_name: str, duration_ms: float, status: str, err: str | None) -> None:
    console = _resolve_console(color=None)
    line = Text()
    line.append("◆ ", style="grey50")
    line.append("spyv.watch  ", style="cyan")
    line.append(fn_name, style="bold")
    line.append("  ")
    line.append(f"{duration_ms:.0f}ms", style="grey50")
    line.append("  ")
    line.append(status, style=_STATUS_STYLE.get(status, "white"))
    if err:
        line.append("  ")
        line.append(err, style="red")
    console.print(line)


def _emit_json(fn_name: str, duration_ms: float, status: str, err: str | None,
               stream: IO[str] | None = None) -> None:
    payload = {
        "event": "watch",
        "fn": fn_name,
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "ts": _now_iso(),
    }
    if err:
        payload["error"] = err
    line = _json.dumps(payload, ensure_ascii=False, default=str)
    target = stream or sys.stderr
    print(line, file=target, flush=True)
    _logger.info(line)


def _emit(fn_name: str, duration_ms: float, status: str, err: str | None) -> None:
    mode = _resolve_output_mode()
    if mode in ("pretty", "both"):
        _emit_pretty(fn_name, duration_ms, status, err)
    if mode in ("json", "both"):
        _emit_json(fn_name, duration_ms, status, err)


def _label_of(fn: Callable[..., Any], override: str | None) -> str:
    if override:
        return override
    module = getattr(fn, "__module__", "")
    name = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "anonymous")
    return f"{module}.{name}" if module and module != "__main__" else name


def watch(fn: F | None = None, *, label: str | None = None) -> Any:
    def _decorate(target: F) -> F:
        resolved_label = _label_of(target, label)

        if asyncio.iscoroutinefunction(target):
            @wraps(target)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                started = time.perf_counter()
                try:
                    result = await target(*args, **kwargs)
                except BaseException as exc:
                    duration_ms = (time.perf_counter() - started) * 1000
                    _emit(resolved_label, duration_ms, "error", f"{type(exc).__name__}: {exc}")
                    raise
                duration_ms = (time.perf_counter() - started) * 1000
                _emit(resolved_label, duration_ms, "ok", None)
                return result

            return _async_wrapper  # type: ignore[return-value]

        @wraps(target)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                result = target(*args, **kwargs)
            except BaseException as exc:
                duration_ms = (time.perf_counter() - started) * 1000
                _emit(resolved_label, duration_ms, "error", f"{type(exc).__name__}: {exc}")
                raise
            duration_ms = (time.perf_counter() - started) * 1000
            _emit(resolved_label, duration_ms, "ok", None)
            return result

        return _sync_wrapper  # type: ignore[return-value]

    if fn is None:
        return _decorate
    return _decorate(fn)


__all__ = ["watch"]
