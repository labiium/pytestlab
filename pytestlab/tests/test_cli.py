import pytest
from typer.testing import CliRunner

from pytestlab.cli import app

runner = CliRunner()


def test_version():
    """Test the --version command."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "PyTestLab" in result.stdout


@pytest.mark.skip(reason="Not implemented yet")
def test_run_command():
    """Placeholder test for the 'run' command."""
    pass


@pytest.mark.skip(reason="Not implemented yet")
def test_list_command():
    """Placeholder test for the 'list' command."""
    pass