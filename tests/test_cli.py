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
