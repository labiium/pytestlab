from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from pytestlab.cli import app
from pytestlab.hardware import lamb_scope
from pytestlab.hardware.lamb_scope import LambScopeSpec
from pytestlab.hardware.lamb_scope import run_lamb_scope_checks
from pytestlab.hardware.lamb_scope import validate_scope_profile
from pytestlab.instruments.scpi_engine import SCPIEngine


class FakeLambBackend:
    instances: list[FakeLambBackend] = []

    def __init__(
        self,
        address=None,
        url=None,
        timeout_ms=None,
        model_name=None,
        serial_number=None,
    ):
        self.address = address
        self.url = url
        self.timeout_ms = timeout_ms
        self.model_name = model_name
        self.serial_number = serial_number
        self.queries: list[str] = []
        self.raw_queries: list[str] = []
        FakeLambBackend.instances.append(self)

    def connect(self):
        return None

    def query(self, command: str, delay=None):
        self.queries.append(command)
        if command == "*IDN?":
            return f"KEYSIGHT TECHNOLOGIES,{self.model_name},MY12345678,1.0"
        if command == ":SYSTem:ERRor?":
            return '+0,"No error"'
        if command == ":ACQuire:SRATe:ANALog?":
            return "+3.20000000E+09"
        if command == ":WAVeform:PREamble?":
            return "+0,+0,+16,+1,+1.0E-9,+0,+0,+1.0E-3,+0,+128"
        if command == ":ACQuire:POINts:ANALog?":
            return "128"
        raise AssertionError(command)

    def query_raw(self, command: str, delay=None):
        self.raw_queries.append(command)
        assert command == ":WAVeform:DATA?"
        return b"#216" + bytes(range(16))


class FakeAsciiWaveformLambBackend(FakeLambBackend):
    def query(self, command: str, delay=None):
        if command == ":WAVeform:PREamble?":
            return "0,6,4,1,1e-9,0,0,1,0,0"
        return super().query(command, delay=delay)

    def query_raw(self, command: str, delay=None):
        self.raw_queries.append(command)
        assert command == ":WAVeform:DATA?"
        return b"-0.1,-0.05,0.05,0.1"


def test_scope_profiles_build_required_readonly_acceptance_aliases():
    rows = validate_scope_profile("keysight/MXR404A") + validate_scope_profile("keysight/HD304MSO")

    assert rows
    assert {row.model for row in rows} == {"MXR404A", "HD304MSO"}
    assert not [row for row in rows if row.status != "pass"]
    assert all((row.command or "").endswith("?") for row in rows)


def test_lamb_scope_checks_record_command_metadata_without_payload(monkeypatch, tmp_path):
    FakeLambBackend.instances.clear()
    monkeypatch.setattr(
        lamb_scope,
        "fetch_lamb_resources",
        lambda url, timeout_ms=5000: (
            [
                "USB::2A8D::9007::MXR404A::MY12345678::INSTR",
                "USB::2A8D::4704::HD304MSO::MY87654321::INSTR",
            ],
            [],
        ),
    )

    report = run_lamb_scope_checks(
        url="http://lamb.example:8000",
        specs=(
            LambScopeSpec(model="MXR404A", profile="keysight/MXR404A"),
            LambScopeSpec(model="HD304MSO", profile="keysight/HD304MSO"),
        ),
        capture_waveform=True,
        output_dir=tmp_path,
        backend_factory=FakeLambBackend,
    )

    assert not report.failures
    assert {row.check for row in report.passes} >= {
        "active_resource_preflight",
        "idn",
        "error_queue",
        "sample_rate",
        "preamble",
        "query_raw_waveform",
    }
    assert len(FakeLambBackend.instances) == 2
    assert all(
        instance.raw_queries == [":WAVeform:DATA?"] for instance in FakeLambBackend.instances
    )

    artifact = Path(report.artifact_path or "")
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    raw_rows = [row for row in payload["rows"] if row["check"] == "query_raw_waveform"]
    assert raw_rows
    assert raw_rows[0]["response_len"] == 20
    assert raw_rows[0]["response_sha256"]
    assert raw_rows[0]["response_preview"] is None
    assert report.waveform_reductions
    assert payload["waveform_reductions"][0]["metrics"]["mean"]["standard_uncertainty"] > 0.0
    assert payload["waveform_reductions"][0]["digital_exports"]["reductions"]["mean"][
        "dcc_xml_sha256"
    ]
    idn_rows = [row for row in payload["rows"] if row["check"] == "idn"]
    assert {row["response_preview"] for row in idn_rows} == {
        "KEYSIGHT TECHNOLOGIES,HD304MSO,MY12345678,1.0",
        "KEYSIGHT TECHNOLOGIES,MXR404A,MY12345678,1.0",
    }


def test_lamb_scope_checks_reduce_ascii_waveform_payloads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lamb_scope,
        "fetch_lamb_resources",
        lambda url, timeout_ms=5000: (
            ["USB::2A8D::9007::MXR404A::MY12345678::INSTR"],
            [],
        ),
    )

    report = run_lamb_scope_checks(
        url="http://lamb.example:8000",
        specs=(LambScopeSpec(model="MXR404A", profile="keysight/MXR404A"),),
        capture_waveform=True,
        output_dir=tmp_path,
        backend_factory=FakeAsciiWaveformLambBackend,
    )

    assert not report.failures
    assert report.waveform_reductions[0]["waveform_encoding"] == "ascii_volts"
    assert report.waveform_reductions[0]["point_count"] == 4
    assert any(row.check == "waveform_reductions" and row.status == "pass" for row in report.rows)


def test_lamb_scope_checks_are_skip_safe_when_non_strict_and_missing(monkeypatch):
    monkeypatch.setattr(lamb_scope, "fetch_lamb_resources", lambda url, timeout_ms=5000: ([], []))

    report = run_lamb_scope_checks(
        url="http://lamb.example:8000",
        specs=(LambScopeSpec(model="MXR404A", profile="keysight/MXR404A"),),
        strict=False,
        backend_factory=FakeLambBackend,
    )

    assert not report.failures
    assert any(
        row.check == "active_resource_preflight" and row.status == "skip" for row in report.rows
    )
    assert any(row.check == "query_raw_waveform" and row.status == "skip" for row in report.rows)


def test_lamb_scope_query_alias_failure_is_structured_not_unbound():
    row = lamb_scope._query_check(
        FakeLambBackend(model_name="MXR404A"),
        SCPIEngine({}),
        "MXR404A",
        "idn",
        "identify",
        "MXR404A",
        strict=False,
    )

    assert row.status == "skip"
    assert row.command is None
    assert "identify" in row.detail


def test_lamb_verify_scopes_cli_requires_explicit_url(monkeypatch):
    monkeypatch.delenv("LAMB_SERVER", raising=False)
    monkeypatch.delenv("PYTESTLAB_LAMB_URL", raising=False)

    result = CliRunner().invoke(app, ["lamb", "verify-scopes"])

    assert result.exit_code == 2
    assert "LAMB URL is required" in result.stdout


def test_lamb_verify_scopes_cli_surfaces_failures(monkeypatch, tmp_path):
    class StubReport:
        lamb_url = "http://lamb.example:8000"
        artifact_path = str(tmp_path / "lamb_scope_check.json")
        rows = [
            lamb_scope.LambScopeRow(
                model="MXR404A",
                check="idn",
                status="fail",
                detail="timeout",
                command="*IDN?",
            )
        ]
        failures = rows
        passes = []
        skips = []

    def fake_run(**kwargs):
        assert kwargs["capture_waveform"] is True
        assert kwargs["strict"] is True
        assert kwargs["output_dir"] == tmp_path
        return StubReport()

    monkeypatch.setattr(lamb_scope, "run_lamb_scope_checks", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "lamb",
            "verify-scopes",
            "--url",
            "http://lamb.example:8000",
            "--capture-waveform",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "LAMB Oscilloscope Verification" in result.stdout
    assert "1 LAMB oscilloscope checks failed" in result.stdout
