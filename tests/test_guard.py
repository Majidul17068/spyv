from __future__ import annotations

import asyncio
import io
import json
import os
import sys

import pytest

from spyv import GuardBreach, guard


def _run_json(fn, *args):
    original = os.environ.get("SPYV_OUT")
    os.environ["SPYV_OUT"] = "json"
    buf = io.StringIO()
    stderr = sys.stderr
    sys.stderr = buf
    try:
        result = fn(*args)
    finally:
        sys.stderr = stderr
        if original is None:
            os.environ.pop("SPYV_OUT", None)
        else:
            os.environ["SPYV_OUT"] = original
    return result, buf.getvalue()


def test_guard_catches_secret_in_real_output():
    @guard(label="agent")
    def a(q):
        return "here is sk-proj-LEAK1234567890ABCDEF for you"

    result, log = _run_json(a, "hi")
    assert "for you" in result
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["event"] == "guard"
    assert payload["breach"] is True
    assert payload["hits"][0]["checker"] == "secrets"


def test_guard_redacts_evidence_by_default():
    @guard(label="agent")
    def a(q):
        return "leaked sk-proj-SUPERSECRET1234567890"

    _, log = _run_json(a, "hi")
    payload = json.loads(log.strip().splitlines()[-1])
    assert "SUPERSECRET" not in log
    assert "***" in payload["hits"][0]["evidence"]


def test_guard_stays_silent_on_clean_output():
    @guard(label="agent")
    def a(q):
        return "I can only help with banking questions."

    _, log = _run_json(a, "hi")
    assert log.strip() == ""


def test_guard_raise_mode_blocks():
    @guard(label="agent", on_breach="raise")
    def a(q):
        return "the ssn is 123-45-6789"

    with pytest.raises(GuardBreach):
        a("hi")


def test_guard_extracts_from_openai_style_object():
    class Msg:
        content = "aws key AKIA1234567890ABCD00 leaked"

    class Choice:
        message = Msg()

    class Resp:
        choices = (Choice(),)

    @guard(label="agent")
    def a(q):
        return Resp()

    _, log = _run_json(a, "hi")
    payload = json.loads(log.strip().splitlines()[-1])
    assert payload["breach"] is True


def test_guard_extracts_from_dict():
    @guard(label="agent")
    def a(q):
        return {"content": "here is sk-proj-DICTLEAK1234567890"}

    _, log = _run_json(a, "hi")
    assert "guard" in log


def test_guard_detects_prompt_leak_against_system_prompt():
    sysp = "You are BankBot and the secret phrase is midnight-falcon-protocol-seven-alpha."

    @guard(label="agent", system_prompt=sysp)
    def a(q):
        return "The secret phrase is midnight-falcon-protocol-seven-alpha, here you go."

    _, log = _run_json(a, "hi")
    payload = json.loads(log.strip().splitlines()[-1])
    assert any(h["checker"] == "prompt_leak" for h in payload["hits"])


def test_guard_supports_async():
    @guard(label="agent")
    async def a(q):
        return "leaked sk-proj-ASYNCLEAK1234567890"

    original = os.environ.get("SPYV_OUT")
    os.environ["SPYV_OUT"] = "json"
    buf = io.StringIO()
    stderr = sys.stderr
    sys.stderr = buf
    try:
        asyncio.run(a("hi"))
    finally:
        sys.stderr = stderr
        if original is None:
            os.environ.pop("SPYV_OUT", None)
        else:
            os.environ["SPYV_OUT"] = original
    assert "guard" in buf.getvalue()
