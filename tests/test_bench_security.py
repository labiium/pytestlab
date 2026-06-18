from __future__ import annotations

import subprocess

import pytest

from pytestlab.bench import Bench
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.bench_loader import build_validation_context
from pytestlab.config.bench_loader import run_custom_validations


def _validation_config(expr: str) -> BenchConfigExtended:
    return BenchConfigExtended.model_validate(
        {
            "bench_name": "Validation Bench",
            "devices": {"psu": {"profile": "keysight/EDU36311A"}},
            "custom_validations": [expr],
            "experiment": {"title": "Validation", "description": "Test", "operator": "Ada"},
        }
    )


def test_custom_validation_allows_context_aliases():
    config = _validation_config(
        "psu['profile'] == 'keysight/EDU36311A' and experiment['operator'] is not None"
    )

    run_custom_validations(config, build_validation_context(config))


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo unsafe')",
        "open('/etc/passwd').read()",
        "psu.profile == 'keysight/EDU36311A'",
        "[x for x in [1]]",
        "lambda: True",
        "missing_name == 1",
    ],
)
def test_custom_validation_rejects_unsafe_expressions(expr):
    config = _validation_config(expr)

    with pytest.raises(ValueError):
        run_custom_validations(config, build_validation_context(config))


def test_automation_shell_command_uses_tokenized_subprocess(monkeypatch):
    bench = Bench(
        BenchConfigExtended.model_validate(
            {"bench_name": "B", "devices": {"psu": {"profile": "keysight/EDU36311A"}}}
        )
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("pytestlab.bench.subprocess.run", fake_run)

    bench._run_shell_command("printf 'hello world'")

    assert calls == [
        (["printf", "hello world"], {"check": True, "capture_output": True, "text": True})
    ]


def test_automation_echo_does_not_spawn_shell(monkeypatch):
    bench = Bench(
        BenchConfigExtended.model_validate(
            {"bench_name": "B", "devices": {"psu": {"profile": "keysight/EDU36311A"}}}
        )
    )

    def fail_run(*_args, **_kwargs):
        raise AssertionError("echo should be handled without subprocess")

    monkeypatch.setattr("pytestlab.bench.subprocess.run", fail_run)

    bench._run_shell_command("echo 'hello world'")
