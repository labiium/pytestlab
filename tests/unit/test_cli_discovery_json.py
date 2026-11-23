import json
import re
from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

import pytestlab.cli as cli


@pytest.mark.parametrize(
    "arguments",
    [
        ["list-operations", "keysight/EDU34450A", "--supported-only"],
        ["describe-operation", "keysight/EDU34450A", "measure"],
        ["list-options", "keysight/EDU34450A", "measure", "function"],
        [
            "list-options",
            "keysight/EDU34450A",
            "measure",
            "range_val",
            "--context",
            '{"function":"dc_voltage"}',
        ],
    ],
)
def test_discovery_defaults_to_json(arguments):
    runner = CliRunner()
    default = runner.invoke(cli.app, ["instrument", *arguments])
    assert default.exit_code == 0
    assert isinstance(json.loads(default.stdout), (list, dict))
    assert "\x1b" not in default.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["list-operations", "missing/no-profile"],
        ["describe-operation", "keysight/EDU34450A", "not_an_operation"],
        ["list-options", "keysight/EDU34450A", "measure", "range_val", "--context", "[]"],
    ],
)
def test_discovery_errors_are_json_by_default(arguments):
    result = CliRunner().invoke(cli.app, ["instrument", *arguments])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"]
    assert "\x1b" not in result.stdout


@pytest.mark.parametrize(
    "terminal,no_color,highlighted",
    [
        (True, False, True),
        (True, True, False),
        (False, False, False),
    ],
)
def test_json_highlighting_never_changes_json_content(monkeypatch, terminal, no_color, highlighted):
    class Output(StringIO):
        def isatty(self):
            return terminal

    output = Output()
    monkeypatch.setattr(cli.sys, "stdout", output)
    monkeypatch.setattr(
        cli,
        "Console",
        lambda **kwargs: Console(width=20, force_terminal=True, color_system="standard", **kwargs),
        raising=False,
    )
    if no_color:
        monkeypatch.setenv("NO_COLOR", "")
    else:
        monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    value = {
        "label": "[red]literal Ω °C :smile: " * 20,
        "supported": True,
        "default": None,
        "value": 0.1,
    }
    cli._print_operation_json(value)
    rendered = output.getvalue()
    assert ("\x1b[" in rendered) is highlighted
    unstyled = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", rendered)
    assert (
        unstyled
        == json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    )
    assert json.loads(unstyled) == value


@pytest.mark.parametrize(
    "arguments",
    [
        ["list-operations", "keysight/EDU34450A"],
        ["describe-operation", "keysight/EDU34450A", "measure"],
        ["list-options", "keysight/EDU34450A", "measure", "function"],
    ],
)
def test_redundant_json_option_is_removed(arguments):
    runner = CliRunner()
    help_result = runner.invoke(cli.app, ["instrument", arguments[0], "--help"])
    assert help_result.exit_code == 0
    assert "--json" not in help_result.stdout
    result = runner.invoke(cli.app, ["instrument", *arguments, "--json"])
    assert result.exit_code == 2
