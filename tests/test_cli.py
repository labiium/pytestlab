import pytest
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
    bench_content = '''
bench_name: "Test Bench"
simulate: true
instruments:
  psu:
    profile: "keysight/EDU36311A"
    address: "SIM::power_supply::1"
'''

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as script_file:
        script_file.write(script_content)
        script_path = script_file.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as bench_file:
        bench_file.write(bench_content)
        bench_path = bench_file.name

    try:
        # Test the run command
        result = runner.invoke(app, [
            "run", script_path,
            "--bench", bench_path,
            "--simulate"
        ])

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
    assert "Available instrument profiles" in result.stdout

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
