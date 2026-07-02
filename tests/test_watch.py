from __future__ import annotations

import asyncio
import io
import json
import os
import sys

import pytest

from spyv import watch


def _run_sync_and_capture(fn, *args, **kwargs):
    original_env = os.environ.get("SPYV_OUT")
    os.environ["SPYV_OUT"] = "json"
    buf = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = buf
    try:
        result = fn(*args, **kwargs)
    finally:
        sys.stderr = original_stderr
        if original_env is None:
            os.environ.pop("SPYV_OUT", None)
        else:
            os.environ["SPYV_OUT"] = original_env
    return result, buf.getvalue()


def _run_async_and_capture(coro):
    original_env = os.environ.get("SPYV_OUT")
    os.environ["SPYV_OUT"] = "json"
    buf = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = buf
    try:
        result = asyncio.run(coro)
    finally:
        sys.stderr = original_stderr
        if original_env is None:
            os.environ.pop("SPYV_OUT", None)
        else:
            os.environ["SPYV_OUT"] = original_env
    return result, buf.getvalue()


def test_watch_emits_one_json_line_on_sync_success():
    @watch
    def add(a: int, b: int) -> int:
        return a + b

    result, log = _run_sync_and_capture(add, 2, 3)
    assert result == 5
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["event"] == "watch"
    assert payload["status"] == "ok"
    assert payload["fn"].endswith("add")
    assert payload["duration_ms"] >= 0
    assert "error" not in payload


def test_watch_captures_exception_and_reraises():
    @watch
    def boom() -> None:
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        _run_sync_and_capture(boom)


def test_watch_emits_error_status_on_exception():
    @watch(label="explode")
    def boom() -> None:
        raise ValueError("kaboom")

    original_env = os.environ.get("SPYV_OUT")
    os.environ["SPYV_OUT"] = "json"
    buf = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = buf
    try:
        with pytest.raises(ValueError):
            boom()
    finally:
        sys.stderr = original_stderr
        if original_env is None:
            os.environ.pop("SPYV_OUT", None)
        else:
            os.environ["SPYV_OUT"] = original_env

    log = buf.getvalue()
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["status"] == "error"
    assert payload["fn"] == "explode"
    assert "ValueError" in payload["error"]
    assert "kaboom" in payload["error"]


def test_watch_supports_async_functions():
    @watch
    async def add_async(a: int, b: int) -> int:
        return a + b

    result, log = _run_async_and_capture(add_async(4, 5))
    assert result == 9
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["event"] == "watch"
    assert payload["status"] == "ok"
    assert payload["fn"].endswith("add_async")


def test_watch_label_override_takes_precedence():
    @watch(label="chat_endpoint")
    def ask(user: str) -> str:
        return user.upper()

    result, log = _run_sync_and_capture(ask, "hi")
    assert result == "HI"
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["fn"] == "chat_endpoint"


def test_watch_returns_wrapped_function_that_preserves_metadata():
    @watch
    def documented() -> int:
        return 42

    assert documented.__name__ == "documented"
    assert callable(documented)
