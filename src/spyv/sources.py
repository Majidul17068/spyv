"""Read Python source the way Python reads it.

``path.read_text(encoding="utf-8")`` is the wrong reader for source code and it
has cost this project real measurements three separate times. Two failure modes:

A **byte-order mark** decodes to a stray ``U+FEFF`` at offset zero. The text is
returned without error, and then ``ast.parse`` raises
``invalid non-printable character U+FEFF``. The file looks unparseable when it is
perfectly valid, so its prompt sites vanish from whatever is being counted and
nothing reports a problem.

A **coding cookie** -- ``# -*- coding: latin-1 -*-`` -- means the file is not
UTF-8 at all. Reading it as UTF-8 either raises or silently mangles the text.

``tokenize.detect_encoding`` implements exactly the rule CPython itself applies:
check for a BOM, then look for a cookie in the first two lines, then fall back to
UTF-8. Every module in this package that reads Python source must come through
here, so that a fourth rediscovery is not possible.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

__all__ = ["decode_source", "read_source"]


def decode_source(raw: bytes) -> str:
    """Decode already-read source bytes using their own declared encoding.

    Callers that need the raw bytes as well -- to hash them for a provenance
    record, say -- read the file once and decode through here, rather than
    reading it twice or reimplementing the rule.
    """
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding)


def read_source(path: str | Path) -> str:
    """Decode a Python file using its own declared encoding.

    Raises whatever ``read_bytes`` raises, plus ``SyntaxError`` when the coding
    cookie names an encoding Python does not have. Callers that are walking a
    corpus should catch ``(OSError, UnicodeError, SyntaxError, ValueError)`` and
    skip, rather than letting one malformed file end a run.
    """
    return decode_source(Path(path).read_bytes())
