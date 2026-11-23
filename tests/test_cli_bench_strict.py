from __future__ import annotations

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from pytestlab import cli_typer
from pytestlab.bench import Bench
from pytestlab.devices import AutoDevice


@pytest.fixture(autouse=True)
def guard_offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("static bench checks must not open benches, construct devices, or use I/O")

    monkeypatch.setattr(Bench, "open", forbidden)
    monkeypatch.setattr(Bench, "_run_automation_hook", forbidden)
    monkeypatch.setattr(AutoDevice, "from_config", forbidden)
    monkeypatch.setattr(AutoDevice, "from_preset", forbidden)
    monkeypatch.setattr(AutoDevice, "from_file", forbidden)
    monkeypatch.setattr(AutoDevice, "_build_backend", forbidden)
    monkeypatch.setattr("pytestlab.bench.prepare_backend_resources", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)


def _descriptor(tmp_path, **kwargs):
    path = tmp_path / "bench.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Static test station",
                "automation": {"pre_experiment": ["echo must not run"]},
                **kwargs,
            }
        )
    )
    return path


def _validate(path, *, strict):
    args = ["bench", "validate", str(path)]
    if strict:
        args.append("--strict")
    return CliRunner().invoke(cli_typer.app, args)


@pytest.mark.parametrize(("rule", "code"), [("False", 1), ("meter['simulate']", 0)])
def test_strict_bench_checks_custom_rules_without_running_hooks(tmp_path, rule, code):
    path = _descriptor(
        tmp_path,
        instruments={"meter": {"profile": "keysight/34470A", "simulate": True}},
        custom_validations=[rule],
    )
    assert _validate(path, strict=False).exit_code == 0
    result = _validate(path, strict=True)
    assert result.exit_code == code, result.output
    if code:
        assert "Custom validation failed" in result.output


@pytest.mark.parametrize(
    ("entry", "profile", "expected_error"),
    [
        ({"backend": {"type": "lamb"}}, None, "explicit nonempty address"),
        ({"backend": {"type": "lamb"}, "address": "  "}, None, "explicit nonempty address"),
        ({"backend": {"type": "lamb", "resource_string": "  "}}, None, "explicit nonempty address"),
        ({"backend": {"type": "lamb"}, "address": "CAMERA::1"}, None, None),
        ({"backend": {"type": "lamb", "resource_string": "CAMERA::1"}}, None, None),
        ({"backend": {"type": "lamb"}}, {}, "explicit nonempty address"),
        ({}, {"backend": {"type": "lamb", "resource_string": "CAMERA::1"}}, None),
        ({}, {"backend": {"type": "lamb"}, "address": "CAMERA::1"}, None),
        (
            {"backend": {"type": "lamb"}},
            {"backend": {"type": "other"}},
            "explicit nonempty address",
        ),
        ({"backend": {"type": "other"}}, {"backend": {"type": "lamb"}}, None),
        ({"simulate": True}, {"backend": {"type": "lamb"}}, None),
        (
            {"backend": {"resource_string": "  "}},
            {"backend": {"type": "lamb", "resource_string": "CAMERA::1"}},
            "explicit nonempty address",
        ),
        (
            {"address": "CAMERA::2"},
            {"backend": {"type": "lamb", "resource_string": "CAMERA::1"}},
            "Conflicting camera address",
        ),
    ],
)
def test_strict_bench_checks_effective_lamb_camera_binding(
    tmp_path, entry, profile, expected_error
):
    if profile is None:
        source = {"device_type": "camera"}
    else:
        (tmp_path / "camera.yaml").write_text(yaml.safe_dump({"device_type": "camera", **profile}))
        source = {"file": "camera.yaml"}
    path = _descriptor(tmp_path, devices={"microscope": {**source, **entry}})

    normal = _validate(path, strict=False)
    assert normal.exit_code == 0, normal.output
    listing = CliRunner().invoke(cli_typer.app, ["bench", "ls", str(path), "--json"])
    assert listing.exit_code == 0, listing.output

    result = _validate(path, strict=True)
    if expected_error:
        assert result.exit_code == 1, result.output
        assert "microscope" in result.output
        assert expected_error in " ".join(result.output.split())
    else:
        assert result.exit_code == 0, result.output
