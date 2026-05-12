from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.verification import VerificationReport
from pytestlab.verification import VerificationResult
from pytestlab.verification import VerificationStatus

runner = CliRunner()


def _make_report(status: VerificationStatus = VerificationStatus.PASS) -> VerificationReport:
    return VerificationReport(
        profile_source="keysight/EDU34450A",
        device_type="multimeter",
        manufacturer="Keysight",
        model="EDU34450A",
        probe_mode="read-only",
        address_override=None,
        results=[
            VerificationResult(
                id="schema.load-profile",
                category="Schema",
                status=status,
                summary="Verification result.",
            )
        ],
    )


def test_instrument_verify_profile_help():
    result = runner.invoke(app, ["instrument", "verify-profile", "--help"])

    assert result.exit_code == 0
    assert "Verify that a real instrument adheres" in result.stdout
    assert "--probe-mode" in result.stdout
    assert "--allow-output-enab" in result.stdout


def test_instrument_verify_profile_success(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, object]] = []
    rendered: list[VerificationReport] = []

    def fake_verify(profile_source: str, **kwargs):
        calls.append({"profile_source": profile_source, **kwargs})
        return _make_report()

    def fake_render(report: VerificationReport):
        rendered.append(report)

    monkeypatch.setattr("pytestlab.verification.verify_instrument_profile", fake_verify)
    monkeypatch.setattr("pytestlab.verification.render_verification_report", fake_render)

    result = runner.invoke(
        app,
        [
            "instrument",
            "verify-profile",
            "keysight/EDU34450A",
            "--address",
            "USB0::1",
            "--probe-mode",
            "safe-write",
            "--allow-output-enable",
            "--timeout-ms",
            "2500",
            "--fail-fast",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "profile_source": "keysight/EDU34450A",
            "address": "USB0::1",
            "probe_mode": "safe-write",
            "allow_output_enable": True,
            "timeout_ms": 2500,
            "fail_fast": True,
        }
    ]
    assert rendered and rendered[0].has_failures is False


def test_instrument_verify_profile_failure_exit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "pytestlab.verification.verify_instrument_profile",
        lambda *args, **kwargs: _make_report(VerificationStatus.FAIL),
    )
    monkeypatch.setattr("pytestlab.verification.render_verification_report", lambda report: None)

    result = runner.invoke(app, ["instrument", "verify-profile", "keysight/EDU34450A"])

    assert result.exit_code == 1


def test_instrument_verify_profile_setup_error(monkeypatch: pytest.MonkeyPatch):
    def fake_verify(*args, **kwargs):
        raise FileNotFoundError("missing profile")

    monkeypatch.setattr("pytestlab.verification.verify_instrument_profile", fake_verify)

    result = runner.invoke(app, ["instrument", "verify-profile", "missing/profile"])

    assert result.exit_code == 2
    assert "was not found" in result.stdout


def test_instrument_verify_profile_rejects_unknown_probe_mode():
    result = runner.invoke(
        app,
        ["instrument", "verify-profile", "keysight/EDU34450A", "--probe-mode", "aggressive"],
    )

    assert result.exit_code == 2
    assert "--probe-mode must be 'read-only' or 'safe-write'" in result.stdout
