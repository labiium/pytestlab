import json
from unittest.mock import Mock

import pytest
import yaml
from rich.text import Text
from typer.testing import CliRunner

from pytestlab.cli import app

runner = CliRunner()


@pytest.mark.parametrize("context", ["{", "[]", "null", "true", "1", '"voltage"'])
def test_discovery_invalid_context_is_structured_json(context):
    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/EDU34450A",
            "measure",
            "range_val",
            "--context",
            context,
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "invalid_context"


def test_discovery_invalid_context_value_preserves_parameter_error():
    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/EDU34450A",
            "measure",
            "range_val",
            "--context",
            '{"function":"bogus"}',
        ],
    )
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "invalid_parameter"
    assert error["parameter"] == "function"
    assert error["value"] == "bogus"


def test_cli_and_python_descriptions_use_canonical_serializer(monkeypatch):
    from pytestlab.cli import _load_instrument_profile
    from pytestlab.instruments.operation_contract import OperationDescription

    calls = []
    original = OperationDescription.to_dict

    def record(self):
        calls.append(self.operation_id)
        return original(self)

    monkeypatch.setattr(OperationDescription, "to_dict", record)
    instrument = _load_instrument_profile("keysight/EDU34450A")
    expected = instrument.describe_operation("measure", context={"function": "dc_voltage"})
    assert "measure" in calls
    calls.clear()
    result = runner.invoke(
        app,
        [
            "instrument",
            "describe-operation",
            "keysight/EDU34450A",
            "measure",
            "--context",
            '{"function":"dc_voltage"}',
        ],
    )
    assert result.exit_code == 0
    assert "measure" in calls
    assert json.loads(result.stdout) == expected


def test_cli_does_not_claim_support_for_unresolved_required_signature(monkeypatch):
    from pytestlab.config.virtual_instrument_config import VirtualInstrumentConfig
    from pytestlab.instruments.operation_contract import OperationDescriptor
    from pytestlab.instruments.VirtualInstrument import VirtualInstrument

    class IncompleteInstrument(VirtualInstrument):
        OPERATION_CONTRACT = (OperationDescriptor("sample"),)

        def sample(self, required_setting):
            raise AssertionError("discovery must not execute methods")

    instrument = IncompleteInstrument(
        backend=Mock(),
        config=VirtualInstrumentConfig(
            manufacturer="Test",
            model="Incomplete",
            device_type="virtual_instrument",
            role="measurement",
        ),
    )
    monkeypatch.setattr("pytestlab.cli_typer._load_instrument_profile", lambda _: instrument)
    result = runner.invoke(app, ["instrument", "describe-operation", "fixture", "sample"])
    assert result.exit_code == 0
    description = json.loads(result.stdout)
    assert description["parameters"] == {}
    assert description["support"]["supported"] is False
    result = runner.invoke(app, ["instrument", "list-operations", "fixture", "--supported-only"])
    assert result.exit_code == 0
    assert "sample" not in json.loads(result.stdout)


def test_version():
    """Test the --version command."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "PyTestLab" in result.stdout


def test_run_command():
    """Test the run command with a simple measurement script."""
    import tempfile
    from pathlib import Path

    # Create a simple test script
    script_content = '''#!/usr/bin/env python3
"""Test measurement script."""

def main(bench):
    """Simple test function that returns measurement data."""
    # Simulate getting instrument ID
    try:
        psu_id = bench.psu.id() if hasattr(bench, 'psu') else "Simulated PSU"
    except:
        psu_id = "Simulated PSU"

    return {
        "measurement_type": "test",
        "instruments": {"psu": psu_id},
        "status": "completed"
    }

if __name__ == "__main__":
    print("Test script - use with pytestlab run")
'''

    # Create a simple bench config
    bench_content = """
bench_name: "Test Bench"
simulate: true
devices:
  psu:
    profile: "keysight/EDU36311A"
    address: "SIM::power_supply::1"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as script_file:
        script_file.write(script_content)
        script_path = script_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as bench_file:
        bench_file.write(bench_content)
        bench_path = bench_file.name

    try:
        # Test the run command
        result = runner.invoke(app, ["run", script_path, "--bench", bench_path, "--simulate"])

        # Clean up
        Path(script_path).unlink()
        Path(bench_path).unlink()

        # Check that it executed without error
        assert result.exit_code == 0
        assert "Running measurement script" in result.stdout
        assert "Script execution completed successfully" in result.stdout

    except Exception:
        # Clean up on error
        Path(script_path).unlink(missing_ok=True)
        Path(bench_path).unlink(missing_ok=True)
        raise


def test_list_command():
    """Test the list command for different resource types."""
    # Test listing profiles
    result = runner.invoke(app, ["list", "profiles"])
    assert result.exit_code == 0
    assert "Available device profiles" in result.stdout

    # Test listing benches
    result = runner.invoke(app, ["list", "benches"])
    assert result.exit_code == 0
    assert "Searching for bench configurations" in result.stdout

    # Test listing examples
    result = runner.invoke(app, ["list", "examples"])
    assert result.exit_code == 0
    assert "Available examples" in result.stdout

    # Test invalid resource type
    result = runner.invoke(app, ["list", "invalid"])
    assert result.exit_code == 1
    assert "Unknown resource type" in result.stdout


def test_visa_list_command(monkeypatch):
    """Test VISA resource discovery without requiring local hardware."""

    class FakeResourceManager:
        def list_resources(self):
            return (
                "USB0::0x0957::0x1798::MY12345678::0::INSTR",
                "TCPIP0::192.168.0.42::inst0::INSTR",
            )

    monkeypatch.setattr(
        "pytestlab.cli_typer._create_visa_resource_manager", lambda: FakeResourceManager()
    )

    result = runner.invoke(app, ["visa", "list"])

    assert result.exit_code == 0
    assert "VISA Resources" in result.stdout
    assert "USB0::0x0957::0x1798::MY12345678::0::INSTR" in result.stdout
    assert "TCPIP0::192.168.0.42::inst0::INSTR" in result.stdout


def test_visa_list_idn_command(monkeypatch):
    """Test optional *IDN? probing for discovered VISA resources."""

    class FakeResource:
        timeout = 0

        def __init__(self, name):
            self.name = name

        def query(self, command):
            assert command == "*IDN?"
            return f"KEYSIGHT,{self.name},MY12345678,1.0\n"

        def close(self):
            pass

    class FakeResourceManager:
        def list_resources(self):
            return ("TCPIP0::192.168.0.42::inst0::INSTR",)

        def open_resource(self, name):
            return FakeResource(name)

    monkeypatch.setattr(
        "pytestlab.cli_typer._create_visa_resource_manager", lambda: FakeResourceManager()
    )

    result = runner.invoke(app, ["visa", "list", "--idn", "--timeout-ms", "1234"])

    assert result.exit_code == 0
    assert "TCPIP0::192.168.0.42::inst0::INSTR" in result.stdout
    assert "KEYSIGHT" in result.stdout
    assert "MY12345678,1.0" in result.stdout


def test_lamb_list_command_preserves_resource_identifiers(monkeypatch):
    """LAMB discovery preserves server-provided resource identifiers."""

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "active": ["USB::2A8D::9007::MXR404A::MY12345678::INSTR"],
                "inactive": ["TCPIP::192.168.0.42::inst0::INSTR"],
            }

    class FakeClient:
        def __init__(self, *, timeout):
            assert timeout == 1.234

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            pass

        def get(self, url):
            assert url == "http://lamb.example:8000/list_resources"
            return FakeResponse()

    monkeypatch.setattr("httpx.Client", FakeClient)

    result = runner.invoke(
        app,
        ["lamb", "list", "--url", "http://lamb.example:8000/", "--timeout-ms", "1234"],
    )

    assert result.exit_code == 0
    assert "LAMB Resources" in result.stdout
    assert "USB::2A8D::9007::MXR404A::MY12345678::INSTR" in result.stdout
    assert "TCPIP::192.168.0.42::inst0::INSTR" in result.stdout


def test_instrument_check_commands_build_only():
    """Test profile SCPI command coverage without touching hardware."""
    result = runner.invoke(app, ["instrument", "check-commands", "keysight/EDU36311A"])

    assert result.exit_code == 0
    assert "Instrument Command Build Check" in result.stdout
    assert "All 14 instrument command checks passed" in result.stdout
    assert "set_voltage" in result.stdout
    assert "measure_voltage" in result.stdout


def test_instrument_check_commands_uses_explicit_parameter_choices():
    """Build-only smoke samples must honour profile-declared enum tokens."""
    result = runner.invoke(app, ["instrument", "check-commands", "keysight/E5071C_VNA"])

    assert result.exit_code == 0
    assert "define_sparameter" in result.stdout
    assert "s_parameter='S11'" in result.stdout


def test_instrument_check_commands_choices_override_generic_fallbacks():
    """Profile-declared choices must drive command-check samples."""
    result = runner.invoke(app, ["instrument", "check-commands", "keysight/EDU33212A"])

    assert result.exit_code == 0
    assert "set_function" in result.stdout
    assert "function='SIN'" in result.stdout


@pytest.mark.parametrize(
    "profile",
    ["keysight/EDU34450A", "keysight/34460A", "keysight/34470A"],
)
def test_dmm_command_checks_use_profile_declared_measurement_examples(profile):
    """Build checks must never invent invalid DMM transport values."""
    from pytestlab.cli import _profile_scpi_command_rows

    _, rows, failures, _, _ = _profile_scpi_command_rows(
        profile,
        strict_response=True,
    )

    measure = next(row for row in rows if row["alias"] == "measure")
    assert failures == 0
    assert measure["status"] == "ok"
    assert measure["sample"] == "function='VOLT:DC', range='AUTO', resolution='DEF'"
    assert "MEASURE:VOLT:DC? AUTO,DEF" in measure["detail"]
    assert all("'TEST'" not in row["sample"] for row in rows if row["kind"] == "query")
    if profile.endswith("34460A"):
        no_args = next(row for row in rows if row["alias"] == "measure_no_args")
        assert no_args["sample"] == "function='DIOD'"
        assert "MEASURE:DIOD?" in no_args["detail"]


def test_instrument_check_commands_fails_without_sample_metadata(tmp_path):
    """The command checker must not invent parameter values from placeholder names."""
    profile_path = tmp_path / "missing_sample_metadata.yaml"
    profile_path.write_text(
        """
manufacturer: Test
model: MissingSampleMetadata
device_type: instrument
role: measurement
scpi:
  commands:
    set_function:
      template: "FUNC {function}"
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["instrument", "check-commands", str(profile_path)])

    assert result.exit_code == 1
    assert "No sample value metadata" in result.stdout
    assert "function" in result.stdout


def test_instrument_check_commands_uses_virtual_profile_choices():
    result = runner.invoke(app, ["instrument", "check-commands", "pytestlab/virtual_instrument"])

    assert result.exit_code == 0
    assert "set_trigger_state" in result.stdout
    assert "state='ARMED'" in result.stdout


def test_instrument_check_operation_contract_reports_hd304mso_as_complete():
    result = runner.invoke(app, ["instrument", "check-operation-contract", "keysight/HD304MSO"])

    assert result.exit_code == 0
    assert "Instrument Operation Contract Check" in result.stdout
    assert "All enabled operation contract checks passed." in result.stdout


def test_instrument_check_operation_contract_strict_accepts_hd304mso_profile():
    result = runner.invoke(
        app, ["instrument", "check-operation-contract", "keysight/HD304MSO", "--strict"]
    )

    assert result.exit_code == 0
    assert "All enabled operation contract checks passed." in result.stdout


def test_instrument_check_operation_contract_strict_accepts_34460a_profile():
    result = runner.invoke(
        app, ["instrument", "check-operation-contract", "keysight/34460A", "--strict"]
    )

    assert result.exit_code == 0
    assert "All enabled operation contract checks passed." in result.stdout


def test_instrument_describe_operation_has_no_transport_diagnostics_flag():
    help_result = runner.invoke(app, ["instrument", "describe-operation", "--help"])
    assert help_result.exit_code == 0
    assert "--include-scpi" not in Text.from_ansi(help_result.stdout).plain

    result = runner.invoke(
        app,
        [
            "instrument",
            "describe-operation",
            "keysight/E5071C_VNA",
            "sparameter_sweep_setup",
            "--include-scpi",
        ],
    )

    assert result.exit_code == 2


def test_instrument_list_options_json():
    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/E5071C_VNA",
            "sparameter_sweep_setup",
            "s_params",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["value"] for item in payload] == ["s11", "s12", "s21", "s22"]
    assert all("token" not in item for item in payload)


def test_cli_and_python_discovery_are_equivalent_with_context():
    from pytestlab import AutoInstrument
    from pytestlab.config.loader import load_device_profile

    config = load_device_profile("keysight/EDU34450A")
    instrument = AutoInstrument.from_config(config)
    context = {"function": "dc_voltage"}
    expected = instrument.list_operation_options("measure", "range_val", context=context)

    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/EDU34450A",
            "measure",
            "range_val",
            "--context",
            json.dumps(context),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == expected


def test_cli_discovery_never_constructs_a_backend(monkeypatch):
    from pytestlab.devices.factory import AutoDevice
    from pytestlab.instruments.backends.sim_backend import SimBackend

    def fail(*args, **kwargs):
        raise AssertionError("discovery attempted runtime construction")

    monkeypatch.setattr(AutoDevice, "_build_backend", fail)
    monkeypatch.setattr(SimBackend, "__init__", fail)

    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/EDU34450A",
            "measure",
            "function",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)


def test_cli_missing_alias_error_uses_incomplete_fixture(tmp_path):
    profile = tmp_path / "incomplete_dmm.yaml"
    profile.write_text(
        """
manufacturer: Test
model: IncompleteDMM
device_type: multimeter
role: measurement
measurement_functions:
  dc_voltage:
    label: DC voltage
    unit: V
    transport: {function_token: 'VOLT:DC', measure_alias: measure}
operation_options:
  measure:
    transport: {query: measure}
    parameters:
      function:
        kind: enum
        options:
          - value: dc_voltage
            transport: {value: 'VOLT:DC'}
        bindings:
          - {alias: query, parameter: function}
scpi:
  queries:
    identify: {template: '*IDN?'}
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            str(profile),
            "measure",
            "function",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "unsupported_options"
    assert "measure" in payload["error"]["message"]


@pytest.mark.parametrize("include_writes", [False, True])
def test_instrument_full_test_can_use_visa_backend(monkeypatch, include_writes):
    """Live VISA queries run, but raw writes are skipped even with --include-writes."""
    calls = {}

    class FakeDevice:
        def connect_backend(self):
            calls["connected"] = True

        def query(self, command, delay=None):
            calls.setdefault("queries", []).append(command)
            if command == "*IDN?":
                return "Keysight,EDU36311A,MY123,1.0"
            if command == "SYST:ERR?":
                return '+0,"No error"'
            if "VOLT" in command or "CURR" in command:
                return "0.0"
            if "OUTP" in command:
                return "OFF"
            return "1"

        def write(self, command):
            calls.setdefault("writes", []).append(command)

        def close(self):
            calls["closed"] = True

    class FakeAutoDevice:
        @classmethod
        def from_config(cls, profile, **kwargs):
            calls["profile"] = profile
            calls["kwargs"] = kwargs
            return FakeDevice()

    monkeypatch.setattr("pytestlab.devices.AutoDevice", FakeAutoDevice)

    result = runner.invoke(
        app,
        [
            "instrument",
            "full-test",
            "keysight/EDU36311A",
            "--backend",
            "visa",
            "--address",
            "USB0::0x0957::0x1234::MY123::INSTR",
            *(["--include-writes"] if include_writes else []),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Real Instrument Full Test" in result.stdout
    assert calls["profile"] == "keysight/EDU36311A"
    assert calls["kwargs"]["simulate"] is False
    assert calls["kwargs"]["backend_type_hint"] == "visa"
    assert calls["kwargs"]["address_override"] == "USB0::0x0957::0x1234::MY123::INSTR"
    assert calls["connected"] is True
    assert calls["closed"] is True
    assert "*IDN?" in calls["queries"]
    assert calls.get("writes") is None
    assert "7 checks skipped" in result.stdout


def test_instrument_full_test_help_explains_live_write_option():
    result = runner.invoke(app, ["instrument", "full-test", "--help"])

    assert result.exit_code == 0, result.output
    help_text = Text.from_ansi(result.stdout).plain
    assert "--include-writes" in help_text
    assert "--yes" not in help_text
    assert "--bench" in help_text
    assert "consume" in help_text and "Unsafe" in help_text


def test_instrument_full_test_requires_address_for_visa():
    """Direct VISA mode needs an explicit resource address."""
    result = runner.invoke(
        app, ["instrument", "full-test", "keysight/EDU36311A", "--backend", "visa"]
    )

    assert result.exit_code == 1
    assert "--address is required for --backend visa" in result.stdout


def test_semantic_operation_validation_invokes_read_methods_and_skips_writes():
    from pytestlab.cli import _semantic_operation_rows
    from pytestlab.instruments.operation_contract import OperationDescriptor

    calls = []

    class Device:
        def operation_descriptors(self):
            return (
                OperationDescriptor("read_value", public_method="read_value", safety_class="read"),
                OperationDescriptor("set_value", public_method="set_value"),
            )

        def describe_operation(self, operation_id):
            return {
                "support": {"supported": True},
                "parameters": {
                    "value": {"kind": "enum", "required": True, "options": [{"value": "sample"}]}
                },
            }

        def read_value(self, value):
            calls.append(("read", value))

        def set_value(self, value):
            calls.append(("write", value))

    rows, failures, warnings, skipped = _semantic_operation_rows(Device(), include_writes=False)
    assert calls == [("read", "sample")]
    assert failures == warnings == 0
    assert skipped == 1
    assert [row["status"] for row in rows] == ["ok", "skip"]


def test_instrument_full_test_can_use_lamb_backend(monkeypatch):
    """The real full test can route through an explicit LAMB backend."""
    calls = {}

    class FakeLambBackend:
        def __init__(
            self,
            address=None,
            url=None,
            timeout_ms=None,
            model_name=None,
            serial_number=None,
        ):
            calls["lamb_backend"] = {
                "address": address,
                "url": url,
                "timeout_ms": timeout_ms,
                "model_name": model_name,
                "serial_number": serial_number,
            }

    class FakeDevice:
        def connect_backend(self):
            calls["connected"] = True

        def query(self, command, delay=None):
            calls.setdefault("queries", []).append(command)
            if command == "*IDN?":
                return "Keysight,EDU36311A,MY123,1.0"
            if command == "SYST:ERR?":
                return '+0,"No error"'
            if "VOLT" in command or "CURR" in command:
                return "0.0"
            if "OUTP" in command:
                return "OFF"
            return "1"

        def write(self, command):
            calls.setdefault("writes", []).append(command)

        def close(self):
            calls["closed"] = True

    class FakeAutoDevice:
        @classmethod
        def from_config(cls, profile, **kwargs):
            calls["profile"] = profile
            calls["kwargs"] = kwargs
            return FakeDevice()

    monkeypatch.setattr("pytestlab.instruments.backends.lamb.LambBackend", FakeLambBackend)
    monkeypatch.setattr("pytestlab.devices.AutoDevice", FakeAutoDevice)

    result = runner.invoke(
        app,
        [
            "instrument",
            "full-test",
            "keysight/EDU36311A",
            "--backend",
            "lamb",
            "--lamb-url",
            "http://localhost:8000",
            "--address",
            "USB0::0x0957::0x1234::MY123::INSTR",
            "--serial-number",
            "MY123",
        ],
    )

    assert result.exit_code == 0
    assert calls["lamb_backend"] == {
        "address": "USB0::0x0957::0x1234::MY123::INSTR",
        "url": "http://localhost:8000",
        "timeout_ms": 5000,
        "model_name": "EDU36311A",
        "serial_number": "MY123",
    }
    assert calls["kwargs"]["simulate"] is False
    assert calls["kwargs"]["backend_override"] is not None
    assert calls["kwargs"]["backend_type_hint"] is None
    assert calls.get("writes") is None
    assert calls["connected"] is True
    assert calls["closed"] is True


def test_instrument_full_test_lamb_auto_connect_without_address(monkeypatch):
    """Default LAMB mode can auto-connect by profile model and optional serial number."""
    calls = {}

    class FakeLambBackend:
        def __init__(
            self,
            address=None,
            url=None,
            timeout_ms=None,
            model_name=None,
            serial_number=None,
        ):
            calls["lamb_backend"] = {
                "address": address,
                "url": url,
                "timeout_ms": timeout_ms,
                "model_name": model_name,
                "serial_number": serial_number,
            }

    class FakeDevice:
        def connect_backend(self):
            calls["connected"] = True

        def query(self, command, delay=None):
            if command == "*IDN?":
                return "Keysight,EDU36311A,MY123,1.0"
            if command == "SYST:ERR?":
                return '+0,"No error"'
            if "VOLT" in command or "CURR" in command:
                return "0.0"
            if "OUTP" in command:
                return "OFF"
            return "1"

        def write(self, command):
            calls.setdefault("writes", []).append(command)

        def close(self):
            calls["closed"] = True

    class FakeAutoDevice:
        @classmethod
        def from_config(cls, profile, **kwargs):
            calls["kwargs"] = kwargs
            return FakeDevice()

    monkeypatch.setattr("pytestlab.instruments.backends.lamb.LambBackend", FakeLambBackend)
    monkeypatch.setattr("pytestlab.devices.AutoDevice", FakeAutoDevice)

    result = runner.invoke(
        app,
        [
            "instrument",
            "full-test",
            "keysight/EDU36311A",
            "--serial",
            "MY123",
        ],
    )

    assert result.exit_code == 0
    assert calls["lamb_backend"] == {
        "address": None,
        "url": None,
        "timeout_ms": 5000,
        "model_name": "EDU36311A",
        "serial_number": "MY123",
    }
    assert calls["kwargs"]["address_override"] is None
    assert calls["kwargs"]["backend_override"] is not None
    assert calls["kwargs"]["backend_type_hint"] is None
    assert calls.get("writes") is None
    assert calls["connected"] is True
    assert calls["closed"] is True


def test_instrument_test_runs_selected_real_hardware_suite(monkeypatch):
    import os
    import runpy
    from pathlib import Path

    calls = {}
    monkeypatch.delenv("PYTESTLAB_INSTRUMENT_TEST_PROFILE", raising=False)

    def fake_pytest_main(args):
        calls["args"] = args
        calls["profile"] = os.environ["PYTESTLAB_INSTRUMENT_TEST_PROFILE"]
        target = args[-1]
        calls["module_profile"] = runpy.run_path(target)["PSU_CONFIG_KEY"]
        return 0

    monkeypatch.setattr("pytest.main", fake_pytest_main)

    result = runner.invoke(app, ["instrument", "test", "keysight/EDU36311A"])

    assert result.exit_code == 0
    assert calls["args"][-2:] == [
        "requires_real_hw",
        str(Path(__file__).parent / "instruments" / "test_psu.py"),
    ]
    assert calls["profile"] == "keysight/EDU36311A"
    assert calls["module_profile"] == "keysight/EDU36311A"
    assert "PYTESTLAB_INSTRUMENT_TEST_PROFILE" not in os.environ


def test_instrument_test_rejects_legacy_kind_mismatch():
    result = runner.invoke(app, ["instrument", "test", "oscilloscope", "keysight/EDU36311A"])

    assert result.exit_code == 1
    assert "does not match profile device_type 'power_supply'" in result.stdout


def test_instrument_test_rejects_all_with_one_profile():
    result = runner.invoke(app, ["instrument", "test", "all", "keysight/EDU36311A"])

    assert result.exit_code == 1
    assert "cannot use one profile" in result.stdout


def test_instrument_test_rejects_profile_without_hardware_suite():
    result = runner.invoke(app, ["instrument", "test", "keysight/E5071C_VNA"])

    assert result.exit_code == 1
    assert "No real-hardware pytest suite" in result.stdout
    assert "device_type 'vna'" in result.stdout


def test_instrument_test_derives_dc_load_suite_from_profile(monkeypatch):
    import os
    import runpy

    calls = {}

    def fake_pytest_main(args):
        calls["target"] = args[-1]
        calls["profile"] = os.environ["PYTESTLAB_INSTRUMENT_TEST_PROFILE"]
        calls["module_profile"] = runpy.run_path(args[-1])["DC_LOAD_CONFIG_KEY"]
        return 0

    monkeypatch.setattr("pytest.main", fake_pytest_main)

    result = runner.invoke(app, ["instrument", "test", "keysight/EL33133A"])

    assert result.exit_code == 0
    assert calls["target"].endswith("tests/instruments/test_dc_load.py")
    assert calls["profile"] == "keysight/EL33133A"
    assert calls["module_profile"] == "keysight/EL33133A"


def test_instrument_check_commands_reports_build_failures(tmp_path):
    """A malformed profile command should fail the build-only command check."""
    profile_path = tmp_path / "bad_profile.yaml"
    profile_path.write_text(
        """
manufacturer: Test
model: BadProfile
device_type: power_supply
channels: []
total_power: 1
line_regulation: 0
load_regulation: 0
scpi:
  commands:
    bad_command:
      defaults: {}
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["instrument", "check-commands", str(profile_path)])

    assert result.exit_code == 1
    assert "Command 'bad_command' missing" in result.stdout
    assert "template/sequence" in result.stdout


def test_full_test_does_not_send_commands_disguised_as_profile_queries(tmp_path, monkeypatch):
    from pytestlab.cli import _profile_scpi_command_rows

    source = tmp_path / "profile.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "scpi": {
                    "commands": {"reset": {"template": "*RST"}},
                    "queries": {
                        "id": {"template": "*IDN?"},
                        "compound": {"template": "OUTP ON; *IDN?"},
                        "sequence": {"sequence": ["OUTP ON", "*IDN?"]},
                        "disguised": {"template": "OUTP ON"},
                        "service": {"template": "*TST?"},
                        "calibrate": {"template": "CAL:ALL?"},
                    },
                }
            }
        )
    )
    commands = []

    class Device:
        def query(self, command):
            commands.append(command)
            return "response"

        def write(self, command):
            pytest.fail(f"Unexpected write: {command}")

    _, rows, failures, warnings, skipped = _profile_scpi_command_rows(
        str(source), device=Device(), include_writes=True, strict_response=True
    )

    assert commands == ["*IDN?"]
    assert failures == warnings == 0
    assert skipped == 6
    assert next(row for row in rows if row["alias"] == "id")["status"] == "ok"

    def no_backend(*args, **kwargs):
        pytest.fail("Custom profiles must not create a live device during full-test")

    monkeypatch.setattr("pytestlab.devices.AutoDevice.from_config", no_backend)
    result = runner.invoke(app, ["instrument", "full-test", str(source), "--include-writes"])
    assert result.exit_code == 0, result.output
    assert "mapping only" in result.stdout
