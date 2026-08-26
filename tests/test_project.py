"""Whole-repository index and cross-module resolution."""

from __future__ import annotations

from spyv.bench.project import ProjectIndex


def _repo(tmp_path, files: dict[str, str]):
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return ProjectIndex(tmp_path)


def test_indexes_modules_functions_and_imports(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/b.py": "from pkg.a import build\n",
    })
    assert "pkg.a" in idx.modules
    assert "build" in idx.modules["pkg.a"].functions
    assert idx.modules["pkg.b"].imports["build"] == ("pkg.a", "build")


def test_resolves_a_callee_in_another_module(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/b.py": "from pkg.a import build\n",
    })
    found = idx.resolve_function("build", idx.modules["pkg.b"])
    assert found is not None
    assert found[0].name == "build"
    assert found[1].dotted == "pkg.a"


def test_resolves_through_an_alias(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/b.py": "from pkg.a import build as mk\n",
    })
    assert idx.resolve_function("mk", idx.modules["pkg.b"]) is not None


def test_resolves_a_relative_import(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/b.py": "from .a import build\n",
    })
    assert idx.resolve_function("build", idx.modules["pkg.b"]) is not None


def test_resolves_a_re_export_through_a_package_init(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "from pkg.a import build\n",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/c.py": "from pkg import build\n",
    })
    assert idx.resolve_function("build", idx.modules["pkg.c"]) is not None


def test_resolves_a_constant_across_modules(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "PROMPT = 'You are a reviewer who audits reports.'\n",
        "pkg/b.py": "from pkg.a import PROMPT\n",
    })
    found = idx.resolve_constant("PROMPT", idx.modules["pkg.b"])
    assert found is not None


def test_unresolvable_name_returns_none_rather_than_guessing(tmp_path):
    idx = _repo(tmp_path, {"a.py": "x = 1\n"})
    assert idx.resolve_function("mystery", idx.modules["a"]) is None


def test_star_imports_are_not_expanded(tmp_path):
    idx = _repo(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "def build():\n    return 'x'\n",
        "pkg/b.py": "from pkg.a import *\n",
    })
    assert idx.resolve_function("build", idx.modules["pkg.b"]) is None


def test_unparseable_file_is_counted_not_fatal(tmp_path):
    idx = _repo(tmp_path, {"good.py": "x = 1\n", "bad.py": "def (:\n"})
    assert idx.stats()["parse_failures"] == 1
    assert "good" in idx.modules


def test_stats_are_reported(tmp_path):
    idx = _repo(tmp_path, {"a.py": "import os\ndef f():\n    return 'x'\n"})
    s = idx.stats()
    assert s["modules"] == 1 and s["functions"] == 1 and s["imports"] == 1
