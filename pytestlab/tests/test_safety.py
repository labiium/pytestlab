# pytestlab/tests/test_safety.py

import pytest
from pytestlab.instruments import PowerSupply
from pytestlab.errors import SafetyLimitError


@pytest.fixture
def psu():
    """A power supply with a simulated backend."""
    return PowerSupply(backend="sim")


def test_apply_safety_limits(psu):
    """Verify that safety limits are correctly applied to instruments."""
    psu.voltage_limit = 5.0
    psu.current_limit = 1.0
    assert psu.voltage_limit == 5.0
    assert psu.current_limit == 1.0


def test_safety_limit_exceeded(psu):
    """Ensure that a SafetyLimitError is raised when a safety limit is exceeded."""
    psu.voltage_limit = 5.0
    with pytest.raises(SafetyLimitError):
        psu.voltage = 6.0


@pytest.mark.skip(reason="Complex scenario, to be implemented later.")
def test_complex_safety_scenario_one():
    """Placeholder for a more complex safety test."""
    pass


@pytest.mark.skip(reason="Complex scenario, to be implemented later.")
def test_complex_safety_scenario_two():
    """Another placeholder for a complex safety test."""
    pass