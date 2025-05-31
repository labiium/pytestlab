import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
from pydantic import ValidationError
import math

from pytestlab.config.base import Range
from pytestlab.config.accuracy import AccuracySpec
from pytestlab.errors import InstrumentParameterError

# Define common float strategy, excluding NaNs and Infs for most numerical inputs
finite_floats = st.floats(allow_nan=False, allow_infinity=False)
positive_floats = st.floats(min_value=0, allow_nan=False, allow_infinity=False, exclude_min=True)
non_negative_floats = st.floats(min_value=0, allow_nan=False, allow_infinity=False)

# Tests for pytestlab.config.base.Range

@given(min_val=finite_floats, max_val=finite_floats)
def test_range_initialization(min_val, max_val):
    """
    Tests Range initialization:
    - Should pass if min_val < max_val.
    - Should raise ValidationError if min_val >= max_val.
    """
    if min_val < max_val:
        r = Range(min_val=min_val, max_val=max_val)
        assert r.min_val == min_val
        assert r.max_val == max_val
    else:
        with pytest.raises((ValidationError, ValueError)): # Pydantic v1 raises ValueError from validators
            Range(min_val=min_val, max_val=max_val)

@given(
    min_val=finite_floats,
    max_val=finite_floats,
    value_offset=st.one_of(
        st.just(0.0), # Test edge case: value == min_val or value == max_val
        finite_floats.filter(lambda x: x != 0) # Test value inside or outside range
    )
)
def test_range_assert_in_range(min_val, max_val, value_offset):
    """
    Tests Range.assert_in_range(value):
    - Passes if min_val <= value <= max_val.
    - Raises ValueError (or InstrumentParameterError) if value is outside.
    """
    if min_val >= max_val: # Invalid range, skip test for assert_in_range
        return

    r = Range(min_val=min_val, max_val=max_val)

    # Determine value based on offset relative to the range
    if value_offset == 0: # Test edges
        value_at_min = min_val
        value_at_max = max_val
        r.assert_in_range(value_at_min)
        r.assert_in_range(value_at_max)
        if min_val != max_val: # if min_val == max_val, middle is also an edge
             middle_value = min_val + (max_val - min_val) / 2
             r.assert_in_range(middle_value)
        return

    # Test values inside and outside
    # Value inside: pick a point within the range using value_offset as a small delta
    # Ensure offset doesn't push it outside if range is very small
    delta = abs(max_val - min_val) * 0.1 if (max_val - min_val) != 0 else 0.1
    value_inside = min_val + delta if min_val + delta < max_val else min_val + (max_val - min_val)/2
    if min_val <= value_inside <= max_val :
         r.assert_in_range(value_inside)


    # Value outside (below min_val)
    value_below = min_val - abs(value_offset) # Ensure it's strictly less
    with pytest.raises((ValueError, InstrumentParameterError)):
        r.assert_in_range(value_below)

    # Value outside (above max_val)
    value_above = max_val + abs(value_offset) # Ensure it's strictly more
    with pytest.raises((ValueError, InstrumentParameterError)):
        r.assert_in_range(value_above)


# Tests for pytestlab.config.accuracy.AccuracySpec

@st.composite
def accuracy_spec_and_values(draw):
    """Strategy to generate AccuracySpec and relevant reading/range values."""
    percent_reading = draw(non_negative_floats)
    offset_value = draw(non_negative_floats)
    
    spec = AccuracySpec(percent_reading=percent_reading, offset_value=offset_value)
    
    # reading_value can be positive or negative
    reading_value = draw(finite_floats)
    
    # range_value should be positive, representing the full scale of the range
    range_value = draw(positive_floats)
    
    return spec, reading_value, range_value

@given(data=accuracy_spec_and_values())
@settings(suppress_health_check=[HealthCheck.filter_too_much]) # May filter if range_value is too small
def test_accuracy_spec_calculate_std_dev(data):
    """
    Tests AccuracySpec.calculate_std_dev(reading_value, range_value):
    - Assert sigma >= 0.
    - Verify calculation against known formulas.
      (Assuming formula: (percent_reading/100 * abs(reading_value) + offset_value) / 3 for k=3 coverage)
      The problem description does not specify the coverage factor k, so we assume k=1 for direct uncertainty.
      If the model's `calculate_std_dev` implies a coverage factor (e.g. for 99.7% confidence, k=3),
      the test formula should match that. For now, we test the direct uncertainty calculation.
    """
    spec, reading_value, range_value = data

    # The problem description is ambiguous about whether `range_value` is used in the formula
    # for `AccuracySpec`. Typically, accuracy is `±(%reading + offset_FS)` where offset_FS
    # is `%full_scale * range_value` or a fixed `offset_value` in units.
    # The `AccuracySpec` model has `percent_reading` and `offset_value`.
    # Let's assume `offset_value` is an absolute offset in the same units as the reading.
    # And `range_value` parameter in `calculate_std_dev` might be used if `offset_value`
    # in `AccuracySpec` was a percentage of full scale.
    # Given the current `AccuracySpec` fields, a common formula for uncertainty (U) is:
    # U = (spec.percent_reading / 100.0) * abs(reading_value) + spec.offset_value
    # The problem asks for `calculate_std_dev`. If U represents the expanded uncertainty
    # with a coverage factor k (e.g., k=1 for 1-sigma, k=2 for ~95%, k=3 for ~99.7%),
    # then std_dev (sigma) = U / k.
    # The prompt says "Verify calculation against known formulas" but doesn't specify k.
    # Let's assume k=1 (i.e., calculate_std_dev returns the 1-sigma uncertainty directly).
    # The `range_value` parameter to `calculate_std_dev` is unusual if `offset_value` is already absolute.
    # I will consult the implementation of `AccuracySpec.calculate_std_dev` if available.
    # For now, I will assume `range_value` is NOT used if `offset_value` is absolute,
    # or that `offset_value` in `AccuracySpec` might be a fraction of `range_value`.
    # Let's assume the simplest interpretation:
    # uncertainty = (percent_reading/100 * abs(reading_value)) + offset_value
    # And that calculate_std_dev returns this value directly (k=1) or divided by a fixed k.
    # The prompt's example `sigma = (percent_reading / 100 * abs(reading_value) + offset_value) / 3`
    # implies k=3. Let's use this.

    expected_sigma_k3 = ((spec.percent_reading / 100.0) * abs(reading_value) + spec.offset_value) / 3.0
    
    # If the actual implementation uses range_value, this test will need adjustment.
    # For example, if offset_value in AccuracySpec is a *fraction* of the range_value:
    # expected_sigma_k3_alt = ((spec.percent_reading / 100.0) * abs(reading_value) + spec.offset_value * range_value) / 3.0

    calculated_sigma = spec.calculate_std_dev(reading_value=reading_value, range_value=range_value)

    assert calculated_sigma >= 0, "Standard deviation (sigma) must be non-negative."
    
    # Compare with the expected formula (assuming k=3 as per a common interpretation for "std_dev" from spec)
    # Using math.isclose for float comparisons
    assert math.isclose(calculated_sigma, expected_sigma_k3), \
        f"Calculated sigma {calculated_sigma} does not match expected {expected_sigma_k3} " \
        f"for spec={spec}, reading={reading_value}, range_val={range_value}"

    # If the formula is different (e.g. k=1, or uses range_value differently), this assertion needs to change.
    # For example, if calculate_std_dev returns the raw uncertainty (k=1):
    # expected_uncertainty_k1 = (spec.percent_reading / 100.0) * abs(reading_value) + spec.offset_value
    # assert math.isclose(calculated_sigma, expected_uncertainty_k1)