"""The shared Python-source reader.

This defect was found and fixed three separate times in this codebase before the
reader was shared, each time after it had silently dropped files from a
measurement. The last test here is the one that matters: it asserts no module
reads Python source as plain UTF-8, so a fourth rediscovery fails CI instead of
a corpus run.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from spyv.sources import decode_source, read_source

SRC = Path(__file__).resolve().parents[1] / "src" / "spyv"


def test_byte_order_mark_does_not_break_parsing(tmp_path):
    """The failure that cost three separate measurements."""
    p = tmp_path / "bom.py"
    p.write_bytes(b"\xef\xbb\xbfSYSTEM_PROMPT = 'you are helpful'\n")

    # What the wrong reader does: decodes fine, then fails to parse.
    with pytest.raises(SyntaxError):
        ast.parse(p.read_text(encoding="utf-8"))

    # What the right one does.
    assert ast.parse(read_source(p)) is not None
    assert not read_source(p).startswith("﻿")


def test_coding_cookie_is_honoured(tmp_path):
    p = tmp_path / "latin.py"
    p.write_bytes(b"# -*- coding: latin-1 -*-\ns = '\xe9'\n")
    assert "\xe9" in read_source(p)


def test_plain_utf8_source_is_unchanged(tmp_path):
    p = tmp_path / "plain.py"
    p.write_text("x = 'héllo'\n", encoding="utf-8")
    assert read_source(p) == "x = 'héllo'\n"


def test_decode_source_matches_read_source(tmp_path):
    """The bytes entry point must not drift from the path one."""
    p = tmp_path / "bom.py"
    p.write_bytes(b"\xef\xbb\xbfx = 1\n")
    assert decode_source(p.read_bytes()) == read_source(p)


def test_unknown_encoding_raises_rather_than_mangling(tmp_path):
    p = tmp_path / "bad.py"
    p.write_bytes(b"# -*- coding: definitely-not-a-codec -*-\nx = 1\n")
    with pytest.raises(SyntaxError):
        read_source(p)


def test_no_module_reads_python_source_as_plain_utf8():
    """Guard against a fourth rediscovery.

    A line that reads a variable named for source code with an explicit utf-8
    encoding is the shape of the bug. Reading YAML, JSON or prompt text that way
    is correct, so only source-shaped reads are flagged.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "sources.py":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if 'read_text(encoding="utf-8")' not in line:
                continue
            target = line.split("=")[0].strip()
            if target.endswith("source") or target.endswith("src"):
                offenders.append(f"{path.relative_to(SRC)}:{n}")
    assert not offenders, (
        "these read Python source as plain UTF-8; use spyv.sources.read_source: "
        + ", ".join(offenders)
    )
