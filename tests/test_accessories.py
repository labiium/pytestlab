from __future__ import annotations

from typing import Any
from typing import cast

import pytest
import yaml
from typer.testing import CliRunner
from uncertainties import ufloat

from pytestlab.accessories import AccessoryProfile
from pytestlab.accessories import BoundAccessory
from pytestlab.accessories import MeasurementChain
from pytestlab.accessories import accessory_correction_quantity
from pytestlab.bench import Bench
from pytestlab.cli import app
from pytestlab.uncertainty.specs import AccuracySpec
from pytestlab.uncertainty import AtomRegistry
from pytestlab.uncertainty import Quantity as MeasurementQuantity
from pytestlab.uncertainty import Distribution as UncertaintyDistribution
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.experiments.database import MeasurementDatabase
from pytestlab.experiments.results import MeasurementResult
from pytestlab.measurement_plan import build_measurement_descriptor
from pytestlab.measurement_plan import prepare_declared_measurements


def test_accessory_profile_loading_separates_presets_from_files(tmp_path):
    preset = AccessoryProfile.from_config("keysight/N2142A")
    assert preset.display_name == "Keysight N2142A"

    local = tmp_path / "probe.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "accessory_type": "probe",
                "model": "LocalProbe",
                "corrections": [
                    {
                        "name": "ratio",
                        "operation": "multiply",
                        "nominal": 10.0,
                        "unit": "",
                    }
                ],
            }
        )
    )
    assert AccessoryProfile.from_file(local).model == "LocalProbe"

    with pytest.raises(ValueError, match="packaged preset keys only"):
        AccessoryProfile.from_config(str(local))
    with pytest.raises(ValueError, match="cannot escape"):
        AccessoryProfile.from_config("../keysight/N2142A")
    with pytest.raises(ValueError, match="YAML file path"):
        AccessoryProfile.from_file("keysight/N2142A")
    with pytest.raises(FileNotFoundError, match="not found"):
        AccessoryProfile.from_config("keysight/DOES_NOT_EXIST")
    with pytest.raises(FileNotFoundError, match="not found"):
        AccessoryProfile.from_file(tmp_path / "missing.yaml")


def test_accessory_profile_validation_errors_are_explicit(tmp_path):
    with pytest.raises(ValueError, match="reviewed accessory presets"):
        AccessoryProfile.model_validate(
            {
                "accessory_type": "probe",
                "model": "Unsourced",
                "review_status": "reviewed",
            }
        )

    malformed = tmp_path / "bad.yaml"
    malformed.write_text("- not\n- a\n- mapping\n")
    with pytest.raises(ValueError, match="YAML mapping"):
        AccessoryProfile.from_file(malformed)

    generic = AccessoryProfile.from_config("generic/rg58_bnc")
    with pytest.raises(ValueError, match="requires parameter"):
        generic.validate_parameters()
    assert generic.with_parameters(length_m=1.0).parameters["length_m"] == 1.0


def test_accessory_schema_rejects_ambiguous_percent_fields():
    with pytest.raises(ValueError, match="Ambiguous accessory correction"):
        AccessoryProfile.model_validate(
            {
                "accessory_type": "probe",
                "model": "BadProbe",
                "corrections": [
                    {
                        "name": "ratio",
                        "operation": "multiply",
                        "nominal": 10.0,
                        "unit": "",
                        "tolerance_percent": 2.0,
                    }
                ],
            }
        )


def test_accessory_correction_quantity_has_explicit_coverage_factor():
    profile = AccessoryProfile.from_config("keysight/N2142A")
    correction = profile.corrections[0]
    quantity = accessory_correction_quantity(correction, accessory=profile)

    assert isinstance(correction.uncertainty, AccuracySpec)
    assert correction.uncertainty.coverage_factor == 1.0
    assert quantity.nominal == 10.0
    assert quantity.u == pytest.approx(0.2)


def test_accessory_correction_quantity_allows_nominal_only_correction():
    profile = AccessoryProfile.model_validate(
        {
            "accessory_type": "adapter",
            "model": "ExactAdapter",
            "corrections": [
                {
                    "name": "ratio",
                    "operation": "multiply",
                    "nominal": 2.0,
                    "unit": "",
                }
            ],
        }
    )

    quantity = accessory_correction_quantity(profile.corrections[0], accessory=profile)

    assert quantity.nominal == 2.0
    assert quantity.u == 0.0


def test_measurement_chain_uses_existing_dimensionless_quantity_arithmetic():
    reg = AtomRegistry()
    raw = MeasurementQuantity.from_atom(
        reg.mint(
            nominal=1.0,
            std_uncertainty=0.1,
            label="instrument",
            unit="V",
            distribution=UncertaintyDistribution.STANDARD,
        ),
        reg,
    )

    corrected = MeasurementChain([AccessoryProfile.from_config("keysight/N2142A")]).apply(raw)

    assert corrected.nominal == pytest.approx(10.0)
    assert corrected.unit in {"V", "volt"}
    # instrument atom + accessory correction atom
    assert len(corrected.budget().entries) == 2


def test_measurement_chain_float_fallback_is_honest():
    raw = MeasurementResult(
        values=1.0,
        instrument="scope",
        units="V",
        measurement_type="Vpp",
    )

    corrected = MeasurementChain([AccessoryProfile.from_config("keysight/N2142A")]).apply(raw)

    chain_envelope = corrected.envelope["measurement_chain"]
    assert corrected.values.nominal == pytest.approx(10.0)
    assert chain_envelope["instrument_budget_status"] == "missing_float_fallback"
    assert "instrument contributed no uncertainty budget" in chain_envelope["instrument_budget_note"]

    direct = MeasurementChain([AccessoryProfile.from_config("keysight/N2142A")]).apply(1.0)
    assert direct.nominal == pytest.approx(10.0)
    # A bare float input carries no instrument uncertainty; only the accessory
    # correction (if any) contributes to the budget.
    assert direct.u >= 0.0


def test_measurement_chain_rejects_array_targets_in_v1():
    import numpy as np

    result = MeasurementResult(
        values=np.array([1.0, 2.0]),
        instrument="scope",
        units="V",
        measurement_type="waveform",
    )

    with pytest.raises(TypeError, match="scalar-only"):
        MeasurementChain([AccessoryProfile.from_config("keysight/N2142A")]).apply(result)


def test_measurement_chain_supports_legacy_ufloat_and_rejects_unknown_objects():
    profile = AccessoryProfile.model_validate(
        {
            "accessory_type": "adapter",
            "model": "OffsetAdapter",
            "corrections": [
                {"name": "offset", "operation": "add", "nominal": 1.0, "unit": "V"},
                {"name": "divider", "operation": "divide", "nominal": 2.0, "unit": ""},
                {"name": "subtract", "operation": "subtract", "nominal": 0.5, "unit": "V"},
            ],
        }
    )

    corrected = MeasurementChain([profile]).apply(
        MeasurementResult(
            values=ufloat(3.0, 0.2),
            instrument="dmm",
            units="V",
            measurement_type="Voltage",
        )
    )

    assert corrected.values.nominal == pytest.approx(1.5)
    assert corrected.envelope["measurement_chain"]["instrument_budget_status"] == "included"

    with pytest.raises(TypeError, match="cannot handle"):
        MeasurementChain([profile]).apply(object())


def test_database_round_trips_measurement_chain_envelope(tmp_path):
    raw = MeasurementResult(
        values=1.0,
        instrument="scope",
        units="V",
        measurement_type="Vpp",
    )
    corrected = MeasurementChain([AccessoryProfile.from_config("keysight/N2142A")]).apply(raw)

    with MeasurementDatabase(tmp_path / "chain") as db:
        key = db.store_measurement(None, corrected)
        restored = db.retrieve_measurement(key)

    assert restored.envelope["measurement_chain"]["steps"][0]["accessory"] == "Keysight N2142A"
    assert isinstance(restored.values, MeasurementQuantity)
    assert restored.values.nominal == pytest.approx(10.0)


def test_database_round_trips_route_and_measurement_chain_envelope(tmp_path):
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Route Bench",
            "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
            "accessories": {"probe": {"profile": "keysight/N2142A"}},
            "routes": {
                "scope_ch1_to_dut_input": {
                    "description": "Scope CH1 through the declared input probe.",
                    "connects": [
                        {
                            "from": "scope.CH1",
                            "to": "dut.input",
                            "path": ["front-panel-bnc", "test-point-vin"],
                        }
                    ],
                    "accessories": ["probe"],
                }
            },
            "measurement_plan": [
                {
                    "name": "input_ripple_vpp",
                    "instrument": "scope",
                    "route": "scope_ch1_to_dut_input",
                    "target": {
                        "kind": "oscilloscope_channel",
                        "channel": 1,
                        "measurement": "vpp",
                    },
                    "accessories": ["probe"],
                }
            ],
        }
    )
    bench = Bench(config)
    bench._device_instances["scope"] = cast(Any, FakeScope())
    corrected = bench.measure("input_ripple_vpp")

    with MeasurementDatabase(tmp_path / "chain_route") as db:
        key = db.store_measurement(None, corrected)
        restored = db.retrieve_measurement(key)

    assert restored.envelope["route"]["name"] == "scope_ch1_to_dut_input"
    assert restored.envelope["route"]["connects"][0]["path"] == [
        "front-panel-bnc",
        "test-point-vin",
    ]
    assert restored.envelope["measurement_chain"]["steps"][0]["accessory"] == "Keysight N2142A"


def test_bound_accessory_provenance_round_trips_through_database(tmp_path):
    bound = BoundAccessory(
        alias="input_probe",
        profile=AccessoryProfile.from_config("keysight/N2142A"),
        profile_key="keysight/N2142A",
        serial_number="MY1234",
        parameters={"attenuation": 10},
        notes="front-panel input chain",
    )
    corrected = MeasurementChain([bound]).apply(
        MeasurementResult(values=1.0, instrument="scope", units="V", measurement_type="Vpp")
    )

    accessory = corrected.envelope["measurement_chain"]["accessories"][0]
    assert accessory["alias"] == "input_probe"
    assert accessory["profile_key"] == "keysight/N2142A"
    assert accessory["profile_source"] == "profile"
    assert accessory["serial_number"] == "MY1234"
    assert accessory["parameters"] == {"attenuation": 10}
    assert accessory["notes"] == "front-panel input chain"

    with MeasurementDatabase(tmp_path / "chain") as db:
        key = db.store_measurement(None, corrected)
        restored = db.retrieve_measurement(key)

    restored_accessory = restored.envelope["measurement_chain"]["accessories"][0]
    assert restored_accessory["alias"] == "input_probe"
    assert restored_accessory["serial_number"] == "MY1234"


def test_measurement_plan_executable_schema_rejects_typos_and_legacy_overlap():
    base = {
        "bench_name": "Accessory Bench",
        "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
    }
    with pytest.raises(ValueError, match="Extra inputs"):
        BenchConfigExtended.model_validate(
            {
                **base,
                "measurement_plan": [
                    {
                        "name": "bad",
                        "instrument": "scope",
                        "targt": {"kind": "oscilloscope_channel"},
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="legacy channel/probe_location"):
        BenchConfigExtended.model_validate(
            {
                **base,
                "measurement_plan": [
                    {
                        "name": "bad",
                        "instrument": "scope",
                        "channel": 1,
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                    }
                ],
            }
        )


def test_measurement_plan_target_compatibility_and_settings_validation():
    legacy = BenchConfigExtended.model_validate(
        {
            "bench_name": "Legacy Bench",
            "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
            "measurement_plan": [
                {
                    "name": "legacy_note",
                    "instrument": "scope",
                    "settings": {"free_form": "still allowed"},
                }
            ],
        }
    ).measurement_plan[0]
    assert legacy.target == "scope"
    assert legacy.target_alias == "scope"
    assert legacy.execution_target is None
    assert legacy.settings == {"free_form": "still allowed"}

    executable_config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Executable Bench",
            "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
            "measurement_plan": [
                {
                    "name": "vdc",
                    "instrument": "dmm",
                    "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                    "settings": {"range": 10, "resolution": 0.001},
                }
            ],
        }
    )
    executable = executable_config.measurement_plan[0]
    assert executable.target == "dmm"
    assert executable.execution_target is not None
    dumped = executable_config.model_dump(by_alias=True, exclude_none=True)
    assert dumped["measurement_plan"][0]["target"]["kind"] == "multimeter_function"
    assert "execution_target" not in dumped["measurement_plan"][0]

    with pytest.raises(ValueError, match="Unsupported settings"):
        BenchConfigExtended.model_validate(
            {
                "bench_name": "Bad Executable Bench",
                "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
                "measurement_plan": [
                    {
                        "name": "vdc",
                        "instrument": "dmm",
                        "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                        "settings": {"resoluton": 0.001},
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="Unsupported settings"):
        BenchConfigExtended.model_validate(
            {
                "bench_name": "Bad Scope Bench",
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "measurement_plan": [
                    {
                        "name": "vpp",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                        "settings": {"range": 10},
                    }
                ],
            }
        )


def test_bench_open_validates_declared_measurements_before_initializing_devices(monkeypatch):
    def fail_initialize(self):
        raise AssertionError("_initialize_devices should not run")

    monkeypatch.setattr(Bench, "_initialize_devices", fail_initialize)

    with pytest.raises(InstrumentConfigurationError, match="channel 99"):
        Bench.open(
            {
                "bench_name": "Invalid Bench",
                "simulate": True,
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "measurement_plan": [
                    {
                        "name": "bad_channel",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 99,
                            "measurement": "vpp",
                        },
                    }
                ],
            }
        )

    with pytest.raises(InstrumentConfigurationError, match="missing_probe"):
        Bench.open(
            {
                "bench_name": "Invalid Bench",
                "simulate": True,
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "measurement_plan": [
                    {
                        "name": "missing_accessory",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                        "accessories": ["missing_probe"],
                    }
                ],
            }
        )


class FakeScope:
    def measure_voltage_peak_to_peak(self, channel: int) -> MeasurementResult:
        assert channel == 1
        value = AccuracySpec(
            offset=0.01,
            offset_unit="V",
            distribution=UncertaintyDistribution.STANDARD,
        ).quantity(1.0, unit="V")
        return MeasurementResult(
            values=value,
            instrument="FakeScope",
            units="V",
            measurement_type="Vpp",
        )


class FakeDMM:
    def measure(self, function: Any, range_val: str | None = None, resolution: str | None = None):
        assert str(function).endswith("VOLTAGE_DC")
        assert isinstance(range_val, str)
        assert isinstance(resolution, str)
        assert range_val.upper() == "10"
        assert resolution.upper() == "0.001"
        return MeasurementResult(
            values=2.0,
            instrument="FakeDMM",
            units="V",
            measurement_type="Voltage",
        )


class FakePSU:
    def read_voltage(self, channel: int) -> float:
        assert channel == 1
        return 5.0

    def read_current(self, channel: int) -> float:
        assert channel == 1
        return 0.5


class FakeLoad:
    def measure_power(self) -> MeasurementResult:
        return MeasurementResult(
            values=3.0,
            instrument="FakeLoad",
            units="W",
            measurement_type="Power",
        )


def test_bench_measure_executes_declared_measurement_without_magic_raw_calls():
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Accessory Bench",
            "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
            "accessories": {"probe": {"profile": "keysight/N2142A"}},
            "measurement_plan": [
                {
                    "name": "input_ripple_vpp",
                    "description": "Input ripple",
                    "instrument": "scope",
                    "target": {
                        "kind": "oscilloscope_channel",
                        "channel": 1,
                        "measurement": "vpp",
                    },
                    "accessories": ["probe"],
                }
            ],
        }
    )
    bench = Bench(config)
    bench._device_instances["scope"] = cast(Any, FakeScope())  # unit-level bench binding

    raw = cast(Any, bench.scope).measure_voltage_peak_to_peak(1)
    declared = bench.measure("input_ripple_vpp")

    assert raw.values.nominal == pytest.approx(1.0)
    assert declared.values.nominal == pytest.approx(10.0)
    assert "DUT -> probe (Keysight N2142A) -> scope CH1" in bench.measurement(
        "input_ripple_vpp"
    ).describe()


def test_declared_measurement_executes_supported_scalar_targets():
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Scalar Bench",
            "instruments": {
                "dmm": {"profile": "keysight/EDU34450A"},
                "psu": {"profile": "keysight/EDU36311A"},
                "load": {"profile": "keysight/EL33133A"},
            },
            "measurement_plan": [
                {
                    "name": "dmm_vdc",
                    "instrument": "dmm",
                    "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                    "settings": {"range": 10, "resolution": 0.001},
                },
                {
                    "name": "psu_v",
                    "instrument": "psu",
                    "target": {
                        "kind": "power_supply_readback",
                        "channel": 1,
                        "quantity": "voltage",
                    },
                },
                {
                    "name": "load_power",
                    "instrument": "load",
                    "target": {"kind": "dc_load_readback", "quantity": "power"},
                },
            ],
        }
    )
    bench = Bench(config)
    bench._device_instances["dmm"] = cast(Any, FakeDMM())
    bench._device_instances["psu"] = cast(Any, FakePSU())
    bench._device_instances["load"] = cast(Any, FakeLoad())

    assert bench.measure("dmm_vdc").values == 2.0
    assert bench.measure("psu_v").values == 5.0
    assert bench.measure("psu_v").units == "V"
    assert bench.measure("load_power").values == 3.0


def test_declared_measurement_validation_reports_target_mismatches_and_files(tmp_path):
    local_probe = tmp_path / "probe.yaml"
    local_probe.write_text(
        yaml.safe_dump(
            {
                "accessory_type": "probe",
                "model": "LocalProbe",
                "compatibility": {"target_kinds": ["oscilloscope_channel"]},
                "corrections": [
                    {"name": "ratio", "operation": "multiply", "nominal": 1.0, "unit": ""}
                ],
            }
        )
    )
    config = BenchConfigExtended.model_validate(
        {
            "bench_name": "Validation Bench",
            "instruments": {
                "scope": {"profile": "keysight/DSOX1204G"},
                "dmm": {"profile": "keysight/EDU34450A"},
                "psu": {"profile": "keysight/EDU36311A"},
                "load": {"profile": "keysight/EL33133A"},
            },
            "accessories": {"local_probe": {"file": "probe.yaml"}},
            "measurement_plan": [
                {
                    "name": "wrong_kind",
                    "instrument": "dmm",
                    "target": {
                        "kind": "oscilloscope_channel",
                        "channel": 1,
                        "measurement": "vpp",
                    },
                    "accessories": ["local_probe"],
                },
                {
                    "name": "valid_psu",
                    "instrument": "psu",
                    "target": {
                        "kind": "power_supply_readback",
                        "channel": 1,
                        "quantity": "current",
                    },
                },
                {
                    "name": "valid_load",
                    "instrument": "load",
                    "target": {"kind": "dc_load_readback", "quantity": "voltage"},
                },
            ],
        }
    )

    prepared = prepare_declared_measurements(config, base_path=tmp_path)

    assert any(
        error.startswith("wrong_kind: oscilloscope target cannot use multimeter")
        for error in prepared.errors
    )
    assert prepared.bound_accessories["local_probe"].profile_file == str(local_probe)


def test_declared_measurement_validation_rejects_incompatible_accessories():
    scope_with_dmm_leads = BenchConfigExtended.model_validate(
        {
            "bench_name": "Invalid Accessory Bench",
            "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
            "accessories": {
                "leads": {
                    "profile": "generic/dmm_test_leads",
                    "parameters": {"lead_resistance_ohm": 0.1},
                }
            },
            "measurement_plan": [
                {
                    "name": "bad_scope_chain",
                    "instrument": "scope",
                    "target": {
                        "kind": "oscilloscope_channel",
                        "channel": 1,
                        "measurement": "vpp",
                    },
                    "accessories": ["leads"],
                }
            ],
        }
    )
    dmm_with_scope_probe = BenchConfigExtended.model_validate(
        {
            "bench_name": "Invalid Accessory Bench",
            "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
            "accessories": {"probe": {"profile": "keysight/N2142A"}},
            "measurement_plan": [
                {
                    "name": "bad_dmm_chain",
                    "instrument": "dmm",
                    "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                    "accessories": ["probe"],
                }
            ],
        }
    )

    scope_errors = prepare_declared_measurements(scope_with_dmm_leads).errors
    assert any("not oscilloscope_channel" in error for error in scope_errors)
    assert "not multimeter_function" in prepare_declared_measurements(dmm_with_scope_probe).errors[0]

    voltage_with_dmm_leads = BenchConfigExtended.model_validate(
        {
            "bench_name": "Invalid Function Bench",
            "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
            "accessories": {
                "leads": {
                    "profile": "generic/dmm_test_leads",
                    "parameters": {"lead_resistance_ohm": 0.1},
                }
            },
            "measurement_plan": [
                {
                    "name": "bad_voltage_chain",
                    "instrument": "dmm",
                    "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                    "accessories": ["leads"],
                }
            ],
        }
    )
    resistance_with_dmm_leads = BenchConfigExtended.model_validate(
        {
            "bench_name": "Valid Function Bench",
            "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
            "accessories": {
                "leads": {
                    "profile": "generic/dmm_test_leads",
                    "parameters": {"lead_resistance_ohm": 0.1},
                }
            },
            "measurement_plan": [
                {
                    "name": "resistance_chain",
                    "instrument": "dmm",
                    "target": {"kind": "multimeter_function", "function": "resistance"},
                    "accessories": ["leads"],
                }
            ],
        }
    )
    assert "not voltage_dc" in prepare_declared_measurements(voltage_with_dmm_leads).errors[0]
    assert prepare_declared_measurements(resistance_with_dmm_leads).errors == []


def test_executable_accessories_require_target_compatibility_metadata(tmp_path):
    missing_compatibility = tmp_path / "missing.yaml"
    unrestricted = tmp_path / "unrestricted.yaml"
    missing_compatibility.write_text(
        yaml.safe_dump(
            {
                "accessory_type": "probe",
                "model": "NoCompatibility",
                "corrections": [
                    {"name": "ratio", "operation": "multiply", "nominal": 1.0, "unit": ""}
                ],
            }
        )
    )
    unrestricted.write_text(
        yaml.safe_dump(
            {
                "accessory_type": "adapter",
                "model": "Unrestricted",
                "compatibility": {"unrestricted_target_kinds": True},
                "corrections": [
                    {"name": "ratio", "operation": "multiply", "nominal": 1.0, "unit": ""}
                ],
            }
        )
    )

    def config_for(accessory_file: str) -> BenchConfigExtended:
        return BenchConfigExtended.model_validate(
            {
                "bench_name": "Compatibility Bench",
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "accessories": {"adapter": {"file": accessory_file}},
                "measurement_plan": [
                    {
                        "name": "vpp",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                        "accessories": ["adapter"],
                    }
                ],
            }
        )

    missing_errors = prepare_declared_measurements(
        config_for("missing.yaml"), base_path=tmp_path
    ).errors
    unrestricted_errors = prepare_declared_measurements(
        config_for("unrestricted.yaml"), base_path=tmp_path
    ).errors
    packaged_errors = prepare_declared_measurements(
        BenchConfigExtended.model_validate(
        {
            "bench_name": "Compatibility Bench",
            "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
            "accessories": {"adapter": {"profile": "keysight/N2142A"}},
            "measurement_plan": [
                {
                    "name": "vpp",
                    "instrument": "scope",
                    "target": {
                        "kind": "oscilloscope_channel",
                        "channel": 1,
                        "measurement": "vpp",
                    },
                    "accessories": ["adapter"],
                }
            ],
        }
        )
    ).errors

    assert "must declare compatibility.target_kinds" in missing_errors[0]
    assert unrestricted_errors == []
    assert packaged_errors == []


def test_cli_validates_and_describes_declared_measurements(tmp_path):
    bench_yaml = tmp_path / "bench.yaml"
    bench_yaml.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Accessory Bench",
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "accessories": {"probe": {"profile": "keysight/N2142A"}},
                "measurement_plan": [
                    {
                        "name": "input_ripple_vpp",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                        "accessories": ["probe"],
                    }
                ],
            }
        )
    )
    runner = CliRunner()

    validate = runner.invoke(app, ["bench", "validate", str(bench_yaml)])
    assert validate.exit_code == 0, validate.stdout

    config = BenchConfigExtended.model_validate(yaml.safe_load(bench_yaml.read_text()))
    prepared = prepare_declared_measurements(config, base_path=tmp_path)
    descriptor = build_measurement_descriptor(config.measurement_plan[0], prepared.bound_accessories)
    assert descriptor.physical_path == ["DUT", "probe (Keysight N2142A)", "scope CH1"]
    assert descriptor.accessories[0]["alias"] == "probe"
    assert descriptor.accessories[0]["profile_key"] == "keysight/N2142A"

    describe = runner.invoke(app, ["bench", "measurement", str(bench_yaml), "input_ripple_vpp"])
    assert describe.exit_code == 0, describe.stdout
    for expected in (descriptor.name, "probe (Keysight N2142A)", "Budget status: known after execution"):
        assert expected in describe.stdout


def test_cli_fails_missing_accessory_alias(tmp_path):
    bench_yaml = tmp_path / "bench.yaml"
    bench_yaml.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Accessory Bench",
                "instruments": {"scope": {"profile": "keysight/DSOX1204G"}},
                "measurement_plan": [
                    {
                        "name": "input_ripple_vpp",
                        "instrument": "scope",
                        "target": {
                            "kind": "oscilloscope_channel",
                            "channel": 1,
                            "measurement": "vpp",
                        },
                        "accessories": ["missing_probe"],
                    }
                ],
            }
        )
    )
    result = CliRunner().invoke(app, ["bench", "validate", str(bench_yaml)])

    assert result.exit_code == 1
    assert "missing_probe" in result.stdout


def test_cli_rejects_incompatible_accessory_chain(tmp_path):
    bench_yaml = tmp_path / "bench.yaml"
    bench_yaml.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Accessory Bench",
                "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
                "accessories": {"probe": {"profile": "keysight/N2142A"}},
                "measurement_plan": [
                    {
                        "name": "bad_dmm_chain",
                        "instrument": "dmm",
                        "target": {"kind": "multimeter_function", "function": "voltage_dc"},
                        "accessories": ["probe"],
                    }
                ],
            }
        )
    )
    runner = CliRunner()

    validate = runner.invoke(app, ["bench", "validate", str(bench_yaml)])
    assert validate.exit_code == 1
    assert "not multimeter_function" in validate.stdout

    measurements = runner.invoke(app, ["bench", "measurements", str(bench_yaml)])
    assert measurements.exit_code == 1
    assert "not multimeter_function" in measurements.stdout
