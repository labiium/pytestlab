"""Regression coverage for profile-owned oscilloscope semantic controls."""

from pathlib import Path

import numpy as np
import pytest
import yaml

from pytestlab import AutoInstrument
from pytestlab.errors import InstrumentDataError
from pytestlab.errors import InstrumentParameterError
from pytestlab.instruments.Oscilloscope import Preamble


@pytest.fixture(scope="module")
def sim_scope():
    scope = AutoInstrument.from_config(
        config_source=str(
            Path(__file__).parents[1] / "instruments" / "sim" / "keysight" / "DSOX1204G.yaml"
        ),
        simulate=True,
    )
    scope.connect_backend()
    yield scope
    scope.close()


def test_scope_controls_expose_profile_semantics(sim_scope, monkeypatch):
    assert {
        item["value"]
        for item in sim_scope.list_operation_options("set_acquisition_type", "acq_type")
    } >= {
        "normal",
        "average",
    }
    assert {
        item["value"] for item in sim_scope.list_operation_options("set_acquisition_mode", "mode")
    } == {
        "real_time",
        "segmented",
    }
    assert "sine" in {
        item["value"] for item in sim_scope.list_operation_options("set_wave_gen_func", "func_type")
    }

    commands = []
    monkeypatch.setattr(sim_scope, "_send_command", commands.append)
    monkeypatch.setattr(sim_scope, "_wait", lambda: None)
    sim_scope.set_acquisition_type("average")
    sim_scope.set_acquisition_mode("segmented")
    sim_scope.set_wave_gen_func("sine")
    sim_scope.set_acquisition_type("normal")
    sim_scope.set_wave_gen_func("square")
    assert commands == [
        ":ACQuire:TYPE AVERage",
        ":ACQuire:MODE SEGMented",
        "WGEN:FUNC SIN",
        ":ACQuire:TYPE NORMal",
        "WGEN:FUNC SQUare",
    ]


@pytest.mark.parametrize(
    ("operation", "parameter", "value"),
    [
        ("set_acquisition_type", "acq_type", "vendor_only"),
        ("set_acquisition_mode", "mode", "vendor_only"),
        ("set_wave_gen_func", "func_type", "vendor_only"),
    ],
)
def test_invalid_scope_semantics_are_rejected_before_io(
    sim_scope, operation, parameter, value, monkeypatch
):
    commands = []
    monkeypatch.setattr(sim_scope, "_send_command", commands.append)
    monkeypatch.setattr(sim_scope, "_wait", lambda: pytest.fail("invalid value attempted I/O"))
    with pytest.raises(InstrumentParameterError):
        getattr(sim_scope, operation)(**{parameter: value})
    assert commands == []


@pytest.mark.parametrize(
    ("operation", "parameter", "command"),
    [
        ("set_acquisition_type", "acq_type", ":ACQuire:TYPE MODE_B"),
        ("set_acquisition_mode", "mode", ":ACQuire:MODE MODE_B"),
        ("set_wave_gen_func", "func_type", "WGEN:FUNC MODE_B"),
    ],
)
def test_custom_scope_semantics_are_not_limited_by_enums(
    operation, parameter, command, monkeypatch
):
    path = Path(__file__).parents[1] / "instruments" / "sim" / "keysight" / "DSOX1204G.yaml"
    profile = yaml.safe_load(path.read_text())
    spec = profile["operation_options"][operation]["parameters"][parameter]
    spec["options"] = [
        {"value": "vendor_a", "transport": {"value": "MODE_A"}},
        {"value": "vendor_b", "transport": {"value": "MODE_B"}},
    ]
    scope = AutoInstrument.from_config(profile, simulate=True)
    commands = []
    monkeypatch.setattr(scope, "_send_command", commands.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)
    options = scope.list_operation_options(operation, parameter)
    getattr(scope, operation)(**{parameter: options[1]["value"]})
    assert commands == [command]
    if operation == "set_acquisition_type":
        monkeypatch.setattr(scope, "_query", lambda _: "MODE_B")
        assert scope.acquisition.get_acquisition_type() == "vendor_b"
        scope.acquisition.set_acquisition_type("vendor_a")
        assert commands[-1] == ":ACQuire:TYPE MODE_A"


@pytest.mark.parametrize(
    ("operation", "parameter", "alias", "placeholder"),
    [
        ("set_acquisition_type", "acq_type", "acq_set_type", "value"),
        ("set_acquisition_mode", "mode", "acq_set_mode", "value"),
        ("set_wave_gen_func", "func_type", "wgen_set_func", "func"),
    ],
)
def test_every_discovered_scope_value_emits_its_profile_command(
    sim_scope, monkeypatch, operation, parameter, alias, placeholder
):
    spec = sim_scope.config.operation_options.parameter(operation, parameter)
    transports = {option.value: option.transport.value for option in spec.options}
    sent = []
    monkeypatch.setattr(sim_scope, "_send_command", sent.append)
    monkeypatch.setattr(sim_scope, "_wait", lambda: None)
    for option in sim_scope.list_operation_options(operation, parameter):
        sent.clear()
        getattr(sim_scope, operation)(option["value"])
        expected = sim_scope._scpi_engine.build(alias, **{placeholder: transports[option["value"]]})
        assert sent == expected


def test_read_only_waveform_path_performs_no_writes(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    monkeypatch.setattr(scope, "_uncertainty_source_key", lambda: "read-only-waveform-test")
    monkeypatch.setattr(
        scope,
        "_send_command",
        lambda command: pytest.fail(f"read-only acquisition attempted write: {command}"),
    )
    monkeypatch.setattr(scope, "get_sampling_rate", lambda: 1.0e9)
    monkeypatch.setattr(
        scope,
        "_query",
        lambda command: {
            ":WAVeform:SOURce?": "CHAN1",
            ":WAVeform:FORMat?": "BYTE",
        }[command],
    )
    monkeypatch.setattr(
        scope,
        "_read_preamble",
        lambda: Preamble(
            format="0",
            type="0",
            points=2,
            xinc=1.0e-9,
            xorg=0.0,
            xref=0.0,
            yinc=1.0,
            yorg=0.0,
            yref=128.0,
        ),
    )
    monkeypatch.setattr(
        scope,
        "_read_wave_data",
        lambda *_args, **_kwargs: np.array([127.0, 129.0]),
    )

    result = scope.read_channels(1, run_after=False, waveform_format="auto")

    assert result.values["Channel 1 (V)"].to_list() == [-1.0, 1.0]


def test_waveform_sources_are_profile_owned_for_non_keysight_tokens(monkeypatch) -> None:
    profile = yaml.safe_load(
        (
            Path(__file__).parents[2] / "pytestlab" / "profiles" / "keysight" / "HD304MSO.yaml"
        ).read_text()
    )
    options = profile["operation_options"]["waveform_readout"]["parameters"]["channel"]["options"]
    for option in options:
        option["transport"]["value"] = f"INPUT_{option['value'].rsplit('_', 1)[1]}"
    scope = AutoInstrument.from_config(profile, simulate=True)

    assert scope._waveform_source_for_channel(2) == "INPUT_2"
    monkeypatch.setattr(scope, "_query", lambda _command: "INPUT_2")
    assert scope._read_current_waveform_source() == 2

    monkeypatch.setattr(scope, "_query", lambda _command: "UNKNOWN")
    with pytest.raises(InstrumentDataError, match="map the current waveform source"):
        scope._read_current_waveform_source()


def test_channel_axis_uses_structural_scale_and_offset_validation(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    sent: list[str] = []
    monkeypatch.setattr(scope, "_send_command", sent.append)
    monkeypatch.setattr(scope, "_wait", lambda: None)

    scope.set_channel_axis(1, 0.5, 0.0)

    assert sent == [":CHANnel1:SCALe 0.5", ":CHANnel1:OFFSet 0.0"]
    sent.clear()
    with pytest.raises(InstrumentParameterError, match="outside the profile-declared range"):
        scope.set_channel_axis(1, -1.0, 0.0)
    assert sent == []


def test_channel_bandwidth_uses_profile_instrument_limit(monkeypatch) -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    sent: list[str] = []
    monkeypatch.setattr(scope, "_send_command", sent.append)

    scope.setup_channel(1, bandwidth_limit=20_000_000)

    assert sent == [":CHANnel1:BANDwidth 20000000.0"]


def test_scope_profiles_preserve_high_resolution_and_mxr_waveforms(monkeypatch) -> None:
    for profile in ("keysight/DSOX1204G", "keysight/HD304MSO"):
        scope = AutoInstrument.from_config(profile, simulate=True)
        sent: list[str] = []
        monkeypatch.setattr(scope, "_send_command", sent.append)
        monkeypatch.setattr(scope, "_wait", lambda: None)
        scope.set_acquisition_type("high_resolution")
        assert sent[-1].endswith("HRESolution")

    mxr = AutoInstrument.from_config("keysight/MXR404A", simulate=True)
    options = {
        option["value"] for option in mxr.list_operation_options("set_wave_gen_func", "func_type")
    }
    assert {"gaussian", "prbs", "arbitrary"} <= options


def test_scope_public_io_methods_have_profile_operation_descriptors() -> None:
    scope = AutoInstrument.from_config("keysight/HD304MSO", simulate=True)
    methods = {descriptor.public_method for descriptor in scope.operation_descriptors()}
    assert {
        "auto_scale",
        "fft_display",
        "measure_phase",
        "measure_frequency",
        "run",
        "stop",
    } <= methods


@pytest.mark.parametrize("profile", ["keysight/MXR404A", "keysight/HD304MSO"])
@pytest.mark.parametrize("channel", [0, 5])
def test_scalar_frequency_rejects_out_of_profile_channels_before_io(
    profile, channel, monkeypatch
) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    monkeypatch.setattr(
        scope, "_query", lambda _query: pytest.fail("invalid channel attempted I/O")
    )
    with pytest.raises(InstrumentParameterError):
        scope.measure_frequency(channel, uncertainty=False)


@pytest.mark.parametrize("profile", ["keysight/MXR404A", "keysight/HD304MSO"])
@pytest.mark.parametrize(
    "response",
    ["nan", "inf", "-inf", "0", "-1", "9.9E37", "-9.9E37", "9.99999E37", "-9.99999E37"],
)
def test_scalar_frequency_rejects_unavailable_readings(profile, response, monkeypatch) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    monkeypatch.setattr(scope, "_query", lambda _query: response)
    with pytest.raises(InstrumentDataError):
        scope.measure_frequency(1, uncertainty=False)


@pytest.mark.parametrize("profile", ["keysight/MXR404A", "keysight/HD304MSO"])
def test_scalar_frequency_does_not_claim_calibrated_uncertainty(profile, monkeypatch) -> None:
    scope = AutoInstrument.from_config(profile, simulate=True)
    monkeypatch.setattr(scope, "_query", lambda _query: "1.00000E3")
    scalar = scope.measure_frequency(2, uncertainty=False)
    assert isinstance(scalar.values, float)
    assert scalar.units == "Hz"

    nominal_only = scope.measure_frequency(2)
    assert nominal_only.units == "Hz"
    assert nominal_only.values.u == 0
    assert nominal_only.values.provenance.provenance_complete is False
    assert nominal_only.values.measurement_model.dof_method == "uncertainty_metadata_missing"
    assert nominal_only.values.measurement_model.function == "measure_frequency"
