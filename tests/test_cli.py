from __future__ import annotations

from click.testing import CliRunner

from spyv import __version__
from spyv.cli import main


def test_version_prints_version_string():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_root_help_lists_test_command():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "test" in result.output


def test_test_help_mentions_expected_flags():
    runner = CliRunner()
    result = runner.invoke(main, ["test", "--help"])
    assert result.exit_code == 0
    assert "--model" in result.output
    assert "--attack" in result.output
    assert "--ci" in result.output
    assert "--out" in result.output


def test_redteam_prints_v01_message_and_exits_3():
    runner = CliRunner()
    result = runner.invoke(main, ["redteam"])
    assert result.exit_code == 3
    assert "v0.1" in result.output


def test_exec_prints_v05_message_and_exits_3():
    runner = CliRunner()
    result = runner.invoke(main, ["exec"])
    assert result.exit_code == 3
    assert "v0.5" in result.output


def test_test_without_model_exits_2_with_helpful_error(tmp_path):
    prompt_file = tmp_path / "prompt.yaml"
    prompt_file.write_text("system: hello\n")
    runner = CliRunner()
    result = runner.invoke(main, ["test", str(prompt_file)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output
    assert "--model" in result.output
