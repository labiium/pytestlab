from __future__ import annotations

from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from pytestlab.bench import Bench
from pytestlab.cli import app
from pytestlab.config.bench_config import BenchConfigExtended
from pytestlab.config.device_config import DeviceRole
from pytestlab.config.switch_matrix_config import SwitchMatrixConfig
from pytestlab.devices import AutoDevice
from pytestlab.devices import SwitchMatrixDevice
from pytestlab.measurement_plan import describe_declared_measurement
from pytestlab.measurement_plan import describe_declared_route
from pytestlab.measurement_plan import prepare_declared_measurements
from pytestlab.measurement_plan import validate_declared_routes


def _backend_writes(backend: Any) -> list[str]:
    return backend.writes


def _route_bench_data() -> dict:
    return {
        "bench_name": "route_demo",
        "simulate": True,
        "instruments": {
            "scope": {"profile": "keysight/DSOX1204G"},
        },
        "accessories": {
            "vin_probe": {"profile": "keysight/N2142A", "serial_number": "P123"},
        },
        "routes": {
            "scope_ch1_to_dut_input": {
                "description": "Scope CH1 is cabled to the DUT input.",
                "connects": [
                    {
                        "from": "scope.CH1",
                        "to": "dut.input",
                        "path": ["front-panel-bnc", "test-point-vin"],
                    }
                ],
                "accessories": ["vin_probe"],
                "settling_time_s": 0.1,
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
                "accessories": ["vin_probe"],
            }
        ],
    }


def test_declared_route_validates_and_describes_measurement_path():
    config = BenchConfigExtended.model_validate(_route_bench_data())

    assert validate_declared_routes(config) == []
    prepared = prepare_declared_measurements(config)
    assert prepared.errors == []

    route_text = describe_declared_route(
        "scope_ch1_to_dut_input", config.routes["scope_ch1_to_dut_input"]
    )
    measurement_text = describe_declared_measurement(
        config.measurement_plan[0],
        prepared.bound_accessories,
        config.routes,
    )

    assert "scope.CH1 -> dut.input" in route_text
    assert "Route: scope_ch1_to_dut_input" in measurement_text
    assert "front-panel-bnc -> test-point-vin" in measurement_text
    assert "Accessory chain" in measurement_text


def test_route_validation_rejects_unknown_endpoint_and_accessory():
    data = _route_bench_data()
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["from"] = "scop.CH1"
    data["routes"]["scope_ch1_to_dut_input"]["accessories"] = ["missing_probe"]
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config)

    assert any("unknown resource 'scop'" in error for error in errors)
    assert any("missing_probe" in error for error in errors)


def test_route_validation_rejects_non_switching_route_devices():
    dut_device = _route_bench_data()
    dut_device["routes"]["scope_ch1_to_dut_input"]["device"] = "dut"
    dut_config = BenchConfigExtended.model_validate(dut_device)

    dut_errors = validate_declared_routes(dut_config)

    assert any("route device 'dut' must be declared under devices" in error for error in dut_errors)

    scope_device = _route_bench_data()
    scope_device["routes"]["scope_ch1_to_dut_input"]["device"] = "scope"
    scope_config = BenchConfigExtended.model_validate(scope_device)

    scope_errors = validate_declared_routes(scope_config)

    assert any("route device 'scope' must be declared under devices" in error for error in scope_errors)


def test_route_validation_rejects_bad_channel_suffix_and_target_mismatch():
    bad_channel = _route_bench_data()
    bad_channel["routes"]["scope_ch1_to_dut_input"]["connects"][0]["from"] = "scope.BAD"
    bad_channel_config = BenchConfigExtended.model_validate(bad_channel)

    bad_channel_errors = validate_declared_routes(bad_channel_config)

    assert any("must use CH<n>" in error for error in bad_channel_errors)

    mismatch = _route_bench_data()
    mismatch["instruments"]["dmm"] = {"profile": "keysight/EDU34450A"}
    mismatch["routes"]["scope_ch1_to_dut_input"]["connects"][0]["from"] = "dmm.V.HI"
    mismatch_config = BenchConfigExtended.model_validate(mismatch)

    mismatch_errors = prepare_declared_measurements(mismatch_config).errors

    assert any(
        "does not include one of the measurement target endpoint" in error
        and "scope.CH1" in error
        for error in mismatch_errors
    )


def test_dmm_generic_hi_endpoint_matches_voltage_target():
    data = {
        "bench_name": "dmm_route",
        "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
        "routes": {
            "dmm_hi_to_dut": {
                "connects": [
                    {"from": "dmm.HI", "to": "dut.input"},
                ],
            }
        },
        "measurement_plan": [
            {
                "name": "input_vdc",
                "instrument": "dmm",
                "route": "dmm_hi_to_dut",
                "target": {"kind": "multimeter_function", "function": "voltage_dc"},
            }
        ],
    }
    config = BenchConfigExtended.model_validate(data)

    assert validate_declared_routes(config) == []
    assert prepare_declared_measurements(config).errors == []


def test_dc_load_routes_are_rejected_until_endpoint_semantics_exist():
    data = _route_bench_data()
    data["instruments"]["load"] = {"profile": "keysight/EL33133A"}
    data["measurement_plan"] = [
        {
            "name": "load_power",
            "instrument": "load",
            "route": "scope_ch1_to_dut_input",
            "target": {"kind": "dc_load_readback", "quantity": "power"},
        }
    ]
    config = BenchConfigExtended.model_validate(data)

    errors = prepare_declared_measurements(config).errors

    assert any("routes are not supported for target kind 'dc_load_readback'" in error for error in errors)


def test_measurement_plan_route_accessories_must_match_applied_chain():
    data = _route_bench_data()
    data["measurement_plan"][0]["accessories"] = []
    config = BenchConfigExtended.model_validate(data)

    errors = prepare_declared_measurements(config).errors

    assert any("physical route provenance and applied uncertainty corrections cannot drift" in error for error in errors)

    reverse_drift = _route_bench_data()
    reverse_drift["routes"]["scope_ch1_to_dut_input"]["accessories"] = []
    reverse_drift_config = BenchConfigExtended.model_validate(reverse_drift)

    reverse_errors = prepare_declared_measurements(reverse_drift_config).errors

    assert any("physical route provenance and applied uncertainty corrections cannot drift" in error for error in reverse_errors)


def test_bench_route_and_measurement_wrappers_are_dry_run(tmp_path):
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(_route_bench_data()))

    bench = Bench.open(path)

    assert "Route: scope_ch1_to_dut_input" in bench.route("scope_ch1_to_dut_input").describe()
    assert "Route: scope_ch1_to_dut_input" in bench.describe_measurement("input_ripple_vpp")
    assert bench.measurement_chain("input_ripple_vpp").accessories[0].alias == "vin_probe"


def test_route_cli_lists_and_describes_routes(tmp_path):
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(_route_bench_data()))
    runner = CliRunner()

    routes = runner.invoke(app, ["bench", "routes", str(path)])
    route = runner.invoke(app, ["bench", "route", str(path), "scope_ch1_to_dut_input"])
    measurement = runner.invoke(app, ["bench", "measurement", str(path), "input_ripple_vpp"])

    assert routes.exit_code == 0, routes.output
    assert route.exit_code == 0, route.output
    assert measurement.exit_code == 0, measurement.output
    assert "scope_ch1_to_dut_input" in routes.output
    assert "scope.CH1 -> dut.input" in route.output
    assert "Route: scope_ch1_to_dut_input" in measurement.output


def _switch_profile() -> dict:
    return {
        "device_type": "switch_matrix",
        "role": "switching",
        "manufacturer": "PyTestLab",
        "model": "MatrixFixture",
        "terminals": ["scope.CH1", "dut.input"],
        "channels": ["M1.C1", "M1.R5"],
        "aliases": {"input_path": "M1.C1"},
        "backend": {"import_path": "tests.test_device_api:build_memory_backend"},
    }


def test_switch_matrix_device_validates_and_applies_route():
    matrix = AutoDevice.from_dict(_switch_profile())
    route = BenchConfigExtended.model_validate(
        {
            "bench_name": "matrix_demo",
            "devices": {"matrix": {"profile": "unused"}},
            "routes": {
                "scope_to_input": {
                    "device": "matrix",
                    "connects": [
                        {
                            "from": "scope.CH1",
                            "to": "dut.input",
                            "path": ["input_path", "M1.R5"],
                        }
                    ],
                    "settling_time_s": 0.2,
                }
            },
        }
    ).routes["scope_to_input"]

    assert isinstance(matrix, SwitchMatrixDevice)
    assert matrix.validate_route(route) == [["M1.C1", "M1.R5"]]
    matrix.apply_route("scope_to_input", route)
    assert matrix._backend.writes == [  # type: ignore[attr-defined]
        "ROUTE:CLOSE M1.C1/M1.R5",
        "ROUTE:SETTLE 0.2",
        "ROUTE:NAME scope_to_input",
    ]


def test_switch_matrix_config_rejects_unknown_alias_target():
    try:
        SwitchMatrixConfig(
            device_type="switch_matrix",
            role=DeviceRole.SWITCHING,
            manufacturer="PyTestLab",
            model="BadMatrix",
            terminals=["scope.CH1"],
            channels=["M1.C1"],
            aliases={"bad": "M9.X"},
        )
    except ValueError as exc:
        assert "unknown channel" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid switch alias to fail")


def test_switch_matrix_config_is_strict_and_requires_channels():
    try:
        SwitchMatrixConfig.model_validate(
            {
                "device_type": "switch_matrix",
                "role": "switching",
                "manufacturer": "PyTestLab",
                "model": "BadMatrix",
                "terminals": ["scope.CH1"],
                "unknown_field": "ignored?",
            }
        )
    except ValueError as exc:
        assert "channels" in str(exc) or "Extra inputs" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected invalid switch profile to fail")


def test_switch_matrix_device_rejects_unknown_terminals_and_allowed_route_mismatch():
    profile = _switch_profile()
    profile["allowed_routes"] = {"scope_to_input": ["scope.CH1", "dut.input"]}
    matrix = AutoDevice.from_dict(profile)
    assert isinstance(matrix, SwitchMatrixDevice)
    route = BenchConfigExtended.model_validate(
        {
            "bench_name": "matrix_demo",
            "devices": {"matrix": {"profile": "unused"}},
            "routes": {
                "scope_to_other": {
                    "device": "matrix",
                    "connects": [
                        {"from": "scope.CH1", "to": "dut.other", "path": ["M1.C1"]},
                    ],
                },
                "scope_to_input": {
                    "device": "matrix",
                    "connects": [
                        {"from": "scope.CH1", "to": "dut.input", "path": ["M1.C1"]},
                    ],
                },
            },
        }
    ).routes

    try:
        matrix.validate_route(route["scope_to_other"], name="scope_to_other")
    except ValueError as exc:
        assert "not declared" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unknown terminal to fail")

    try:
        matrix.validate_route(route["scope_to_input"])
    except ValueError as exc:
        assert "Route name is required" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected unnamed allowed route validation to fail")

    # The named route stays within the profile's allowed terminal set.
    assert matrix.validate_route(route["scope_to_input"], name="scope_to_input") == [["M1.C1"]]


def test_switch_matrix_exclusive_route_opens_existing_paths():
    profile = _switch_profile()
    profile["exclusive_groups"] = {"measurement_path": ["scope_to_input"]}
    matrix = AutoDevice.from_dict(profile)
    assert isinstance(matrix, SwitchMatrixDevice)
    route = BenchConfigExtended.model_validate(
        {
            "bench_name": "matrix_demo",
            "devices": {"matrix": {"profile": "unused"}},
            "routes": {
                "scope_to_input": {
                    "device": "matrix",
                    "exclusive_group": "measurement_path",
                    "connects": [
                        {"from": "scope.CH1", "to": "dut.input", "path": ["M1.C1"]},
                    ],
                },
            },
        }
    ).routes["scope_to_input"]

    matrix.apply_route("scope_to_input", route)

    assert _backend_writes(matrix._backend)[:2] == ["ROUTE:OPEN:ALL", "ROUTE:CLOSE M1.C1"]
    assert matrix.route_state()["active_route"] == "scope_to_input"


def test_route_validation_reports_endpoint_profile_load_failure(tmp_path):
    data = _route_bench_data()
    data["instruments"]["scope"] = {"file": "missing-scope.yaml"}
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config, base_path=tmp_path)

    assert any("failed to load route endpoint resource 'scope' profile" in error for error in errors)


def test_route_validation_checks_switch_matrix_paths(tmp_path):
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"file": str(matrix_profile), "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M9.BAD"]
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config)

    assert any("invalid switch route" in error for error in errors)


def test_route_validation_enforces_switch_allowed_routes(tmp_path):
    profile = _switch_profile()
    profile["allowed_routes"] = {"different_route": ["scope.CH1", "dut.input"]}
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(profile))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"file": str(matrix_profile), "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1"]
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config)

    assert any("not declared in allowed_routes" in error for error in errors)


def test_route_validation_rejects_switch_matrix_under_instruments(tmp_path):
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["instruments"]["matrix"] = {"file": str(matrix_profile), "simulate": False}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1"]
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config)

    assert any("route device 'matrix' must be declared under devices" in error for error in errors)


def test_route_validation_checks_dut_terminals_against_switch_profile(tmp_path):
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"file": str(matrix_profile), "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["to"] = "dut.other"
    config = BenchConfigExtended.model_validate(data)

    errors = validate_declared_routes(config)

    assert any("dut.other" in error and "switch terminals" in error for error in errors)


def test_bench_route_apply_uses_switch_matrix_device(tmp_path):
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"file": str(matrix_profile), "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1", "M1.R5"]
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))

    bench = Bench.open(path)
    bench.route("scope_ch1_to_dut_input").apply()

    assert bench.matrix._backend.writes[:1] == [  # type: ignore[attr-defined]
        "ROUTE:CLOSE M1.C1/M1.R5"
    ]


def test_bench_warns_when_profile_is_used_as_local_file_path(tmp_path):
    matrix_profile = tmp_path / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"profile": str(matrix_profile), "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1", "M1.R5"]

    with pytest.warns(DeprecationWarning, match="Use file: for local YAML/JSON profiles"):
        bench = Bench.open(data)

    bench.route("scope_ch1_to_dut_input").apply()
    assert bench.matrix._backend.writes[:1] == [  # type: ignore[attr-defined]
        "ROUTE:CLOSE M1.C1/M1.R5"
    ]


def test_route_cli_strict_validate_reports_route_errors(tmp_path):
    data = _route_bench_data()
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["from"] = "scope.BAD"
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))
    runner = CliRunner()

    result = runner.invoke(app, ["bench", "validate", str(path), "--strict"])

    assert result.exit_code == 1
    assert "Measurement plan validation failed" in result.output
    assert "Strict route validation failed" in result.output


def test_route_cli_non_strict_skips_pre_hardware_route_validation(tmp_path):
    data = _route_bench_data()
    data["measurement_plan"] = []
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["from"] = "scope.BAD"
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))
    runner = CliRunner()

    non_strict = runner.invoke(app, ["bench", "validate", str(path)])
    strict = runner.invoke(app, ["bench", "validate", str(path), "--strict"])

    assert non_strict.exit_code == 0, non_strict.output
    assert "syntax loaded; use --strict" in non_strict.output
    assert strict.exit_code == 1
    assert "Strict route validation failed" in strict.output
    assert "scope.BAD" in strict.output


def test_route_cli_resolves_switch_profile_files_relative_to_bench_yaml(tmp_path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir()
    matrix_profile = devices_dir / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"file": "devices/matrix.yaml", "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1", "M1.R5"]
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))
    runner = CliRunner()

    routes = runner.invoke(app, ["bench", "routes", str(path)])
    route = runner.invoke(app, ["bench", "route", str(path), "scope_ch1_to_dut_input"])

    assert routes.exit_code == 0, routes.output
    assert route.exit_code == 0, route.output
    assert "scope_ch1_to_dut_input" in routes.output


def test_relative_deprecated_profile_paths_resolve_during_validation_and_open(tmp_path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir()
    matrix_profile = devices_dir / "matrix.yaml"
    matrix_profile.write_text(yaml.safe_dump(_switch_profile()))
    data = _route_bench_data()
    data["devices"] = {"matrix": {"profile": "devices/matrix.yaml", "simulate": False}}
    data["routes"]["scope_ch1_to_dut_input"]["device"] = "matrix"
    data["routes"]["scope_ch1_to_dut_input"]["connects"][0]["path"] = ["M1.C1", "M1.R5"]
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))

    config = BenchConfigExtended.model_validate(data)

    assert validate_declared_routes(config, base_path=tmp_path) == []
    assert Bench(config, base_path=tmp_path).measurement_chain("input_ripple_vpp").accessories
    with pytest.warns(DeprecationWarning, match="Use file: for local YAML/JSON profiles"):
        bench = Bench.open(path)
    bench.route("scope_ch1_to_dut_input").apply()
    assert _backend_writes(bench.matrix._backend)[:1] == ["ROUTE:CLOSE M1.C1/M1.R5"]


def test_bench_packaged_profile_key_ignores_same_named_local_directory(tmp_path):
    shadow = tmp_path / "keysight" / "EDU34450A"
    shadow.mkdir(parents=True)
    data = {
        "bench_name": "shadowed_preset",
        "simulate": True,
        "instruments": {"dmm": {"profile": "keysight/EDU34450A"}},
    }
    path = tmp_path / "bench.yaml"
    path.write_text(yaml.safe_dump(data))
    runner = CliRunner()

    validate = runner.invoke(app, ["bench", "validate", str(path), "--strict"])
    bench = Bench.open(path)

    assert validate.exit_code == 0, validate.output
    assert bench.dmm.config.model == "EDU34450A"
