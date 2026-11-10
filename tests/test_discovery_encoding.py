"""Discovery must read a file the way Python does.

This is the product path, not the measurement one: what `spyv scan` reports on
a user's codebase. A byte-order-marked module used to be skipped silently, so a
scan could report no prompts in a file that has them -- a security tool saying
"nothing here" about something it could not read.

The measurement side is covered by tests/test_sources.py. These tests pin the
behaviour a user actually sees.
"""

from __future__ import annotations

from spyv.discovery import discover

PROMPT = 'SYSTEM_PROMPT = "You are a careful assistant. Answer only from context."\n'


def test_byte_order_marked_module_is_scanned(tmp_path):
    (tmp_path / "agent.py").write_bytes(b"\xef\xbb\xbf" + PROMPT.encode("utf-8"))

    prompts, files_scanned = discover(tmp_path)

    assert files_scanned == 1, "the BOM'd file was skipped entirely"
    assert any("careful assistant" in p.system_prompt for p in prompts)


def test_bom_and_plain_modules_give_the_same_result(tmp_path):
    """The mark is an encoding detail; it must not change what is found."""
    plain = tmp_path / "plain"
    bom = tmp_path / "bom"
    plain.mkdir()
    bom.mkdir()
    (plain / "agent.py").write_bytes(PROMPT.encode("utf-8"))
    (bom / "agent.py").write_bytes(b"\xef\xbb\xbf" + PROMPT.encode("utf-8"))

    plain_texts = sorted(p.system_prompt for p in discover(plain)[0])
    bom_texts = sorted(p.system_prompt for p in discover(bom)[0])

    assert plain_texts == bom_texts
    assert plain_texts, "fixture found nothing, so the comparison proves nothing"


def test_coding_cookie_module_is_scanned(tmp_path):
    (tmp_path / "agent.py").write_bytes(
        b"# -*- coding: latin-1 -*-\n" + PROMPT.encode("latin-1")
    )

    prompts, files_scanned = discover(tmp_path)

    assert files_scanned == 1
    assert any("careful assistant" in p.system_prompt for p in prompts)


def test_undecodable_module_is_skipped_without_crashing(tmp_path):
    """One unreadable file must not end a scan of the rest."""
    (tmp_path / "broken.py").write_bytes(b"# -*- coding: not-a-real-codec -*-\nx = 1\n")
    (tmp_path / "agent.py").write_bytes(PROMPT.encode("utf-8"))

    prompts, files_scanned = discover(tmp_path)

    assert files_scanned == 1, "the readable file should still be scanned"
    assert any("careful assistant" in p.system_prompt for p in prompts)
