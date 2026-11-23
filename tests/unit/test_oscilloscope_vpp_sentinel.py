from __future__ import annotations

import pytest

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentDataError

SCOPE_PROFILES = ("keysight/MXR404A", "keysight/DSOX1204G")
SENTINELS = ("9.9e37", "+9.9e37", "-9.9e37", "9.99999e37", "-9.99999e37")


@pytest.mark.parametrize("profile", SCOPE_PROFILES)
@pytest.mark.parametrize("raw_response", SENTINELS)
def test_vpp_documented_unavailable_values_raise_data_error_with_raw_response(
    profile: str, raw_response: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    monkeypatch.setattr(scope, "_query", lambda _command: raw_response)

    with pytest.raises(InstrumentDataError) as raised:
        scope.measure_voltage_peak_to_peak(1, uncertainty=False)

    assert raised.value.instrument == scope.config.model
    assert raw_response in raised.value.message


@pytest.mark.parametrize("profile", SCOPE_PROFILES)
@pytest.mark.parametrize("raw_response", ("0", "-1.25", "2.5", "9.899999e37"))
def test_vpp_finite_values_including_zero_and_negative_remain_measurements(
    profile: str, raw_response: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    monkeypatch.setattr(scope, "_query", lambda _command: raw_response)

    result = scope.measure_voltage_peak_to_peak(1, uncertainty=False)

    assert result.nominal == pytest.approx(float(raw_response))


@pytest.mark.parametrize("profile", SCOPE_PROFILES)
def test_vpp_can_be_retried_after_unavailable_measurement(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    responses = iter(("9.99999e37", "3.25"))
    monkeypatch.setattr(scope, "_query", lambda _command: next(responses))

    with pytest.raises(InstrumentDataError):
        scope.measure_voltage_peak_to_peak(1, uncertainty=False)

    result = scope.measure_voltage_peak_to_peak(1, uncertainty=False)
    assert result.nominal == pytest.approx(3.25)
