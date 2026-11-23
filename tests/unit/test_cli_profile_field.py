import json

from typer.testing import CliRunner

from pytestlab.cli import app


def test_profile_show_field_emits_selected_json_without_ansi(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "measurement_accuracy:\n  dc_voltage:\n    range_terms: [0.001, 0.002]\n"
        "channels:\n  - name: CH1\n    enabled: false\n"
    )

    result = CliRunner().invoke(
        app,
        ["profile", "show", str(profile), "--field", "measurement_accuracy.dc_voltage.range_terms"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [0.001, 0.002]
    assert "\x1b" not in result.stdout


def test_profile_show_without_field_keeps_full_yaml_output(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text("model: Example\nmeasurement_accuracy:\n  dc_voltage: 0.001\n")

    result = CliRunner().invoke(app, ["profile", "show", str(profile)])

    assert result.exit_code == 0
    assert "Profile:" in result.stdout
    assert "measurement_accuracy" in result.stdout
    assert "dc_voltage" in result.stdout


def test_profile_show_field_supports_list_indexes_and_falsy_values(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "channels:\n  - name: CH1\n    enabled: false\n  - name: CH2\n    enabled: 0\n"
        "empty: []\nmissing_value: null\n"
    )
    runner = CliRunner()

    false_result = runner.invoke(
        app, ["profile", "show", str(profile), "--field", "channels.0.enabled"]
    )
    zero_result = runner.invoke(
        app, ["profile", "show", str(profile), "--field", "channels.1.enabled"]
    )
    empty_result = runner.invoke(app, ["profile", "show", str(profile), "--field", "empty"])
    null_result = runner.invoke(app, ["profile", "show", str(profile), "--field", "missing_value"])

    assert false_result.exit_code == 0
    assert json.loads(false_result.stdout) is False
    assert zero_result.exit_code == 0
    assert json.loads(zero_result.stdout) == 0
    assert empty_result.exit_code == 0
    assert json.loads(empty_result.stdout) == []
    assert null_result.exit_code == 0
    assert json.loads(null_result.stdout) is None


def test_profile_show_missing_field_is_json_error_without_profile_dump(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text("model: Example\nmeasurement_accuracy: {}\n")

    result = CliRunner().invoke(
        app, ["profile", "show", str(profile), "--field", "measurement_accuracy.missing"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "profile_field_not_found"
    assert payload["error"]["field"] == "measurement_accuracy.missing"
    assert "model" not in payload


def test_profile_show_field_does_not_construct_instrument_backend(monkeypatch):
    from pytestlab.devices.factory import AutoDevice

    def fail(*args, **kwargs):
        raise AssertionError("profile field inspection constructed a backend")

    monkeypatch.setattr(AutoDevice, "_build_backend", fail)
    result = CliRunner().invoke(
        app,
        ["profile", "show", "keysight/MXR404A", "--field", "measurement_accuracy"],
    )

    assert result.exit_code == 0
    assert isinstance(json.loads(result.stdout), dict)
