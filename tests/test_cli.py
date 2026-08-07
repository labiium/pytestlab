import json

from typer.testing import CliRunner

from pytestlab.cli import app

runner = CliRunner()


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
        "pytestlab.cli._create_visa_resource_manager", lambda: FakeResourceManager()
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
        "pytestlab.cli._create_visa_resource_manager", lambda: FakeResourceManager()
    )

    result = runner.invoke(app, ["visa", "list", "--idn", "--timeout-ms", "1234"])

    assert result.exit_code == 0
    assert "TCPIP0::192.168.0.42::inst0::INSTR" in result.stdout
    assert "KEYSIGHT" in result.stdout
    assert "MY12345678,1.0" in result.stdout


def test_instrument_check_commands_build_only():
    """Test profile SCPI command coverage without touching hardware."""
    result = runner.invoke(app, ["instrument", "check-commands", "keysight/EDU36311A"])

    assert result.exit_code == 0
    assert "Instrument Command Build Check" in result.stdout
    assert "All 10 instrument command checks passed" in result.stdout
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


def test_instrument_check_operation_contract_reports_enabled_missing_aliases():
    result = runner.invoke(app, ["instrument", "check-operation-contract", "keysight/HD304MSO"])

    assert result.exit_code == 0
    assert "Instrument Operation Contract Check" in result.stdout
    assert "warn" in result.stdout


def test_instrument_check_operation_contract_strict_allows_optional_missing_aliases():
    result = runner.invoke(
        app, ["instrument", "check-operation-contract", "keysight/HD304MSO", "--strict"]
    )

    assert result.exit_code == 0
    assert "warn" in result.stdout


def test_instrument_check_operation_contract_strict_fails_on_required_missing_aliases():
    result = runner.invoke(
        app, ["instrument", "check-operation-contract", "keysight/34460A", "--strict"]
    )

    assert result.exit_code == 1
    assert "required enabled operations miss SCPI aliases" in result.stdout


def test_instrument_describe_operation_include_scpi_json():
    result = runner.invoke(
        app,
        [
            "instrument",
            "describe-operation",
            "keysight/E5071C_VNA",
            "sparameter_sweep_setup",
            "--include-scpi",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["operation_id"] == "sparameter_sweep_setup"
    assert "define_sparameter" in payload["scpi"]
    assert payload["scpi"]["define_sparameter"]["parameters"]["s_parameter"]["kind"] == "enum"


def test_instrument_list_options_json():
    result = runner.invoke(
        app,
        [
            "instrument",
            "list-options",
            "keysight/E5071C_VNA",
            "sparameter_sweep_setup",
            "s_parameter",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["token"] for item in payload] == ["S11", "S12", "S21", "S22"]


def test_instrument_full_test_can_use_visa_backend(monkeypatch):
    """The real full test can route through direct VISA when explicitly requested."""
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
        ],
    )

    assert result.exit_code == 0
    assert "Real Instrument Full Test" in result.stdout
    assert "5 write commands skipped" in result.stdout
    assert calls["profile"] == "keysight/EDU36311A"
    assert calls["kwargs"]["simulate"] is False
    assert calls["kwargs"]["backend_type_hint"] == "visa"
    assert calls["kwargs"]["address_override"] == "USB0::0x0957::0x1234::MY123::INSTR"
    assert calls["connected"] is True
    assert calls["closed"] is True
    assert calls.get("writes") is None
    assert "*IDN?" in calls["queries"]


def test_instrument_full_test_requires_yes_for_writes():
    """Real write aliases require explicit confirmation."""
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
            "--include-writes",
        ],
    )

    assert result.exit_code == 1
    assert "Refusing to execute write commands without --yes" in result.stdout


def test_instrument_full_test_requires_address_for_visa():
    """Direct VISA mode needs an explicit resource address."""
    result = runner.invoke(
        app, ["instrument", "full-test", "keysight/EDU36311A", "--backend", "visa"]
    )

    assert result.exit_code == 1
    assert "--address is required for --backend visa" in result.stdout


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
