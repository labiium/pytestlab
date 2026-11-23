from __future__ import annotations

import json
import shlex
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from pytestlab.cli import app


def _bench_yaml(
    tmp_path: Path,
    *,
    cameras: tuple[str, ...] = ("camera",),
    bad_profile: bool = True,
) -> Path:
    marker = tmp_path / "automation-ran"
    devices = {
        alias: {
            "device_type": "camera",
            "address": f"{alias}-id",
            "simulate": False,
            "backend": {
                "type": "lamb",
                "url": "http://lamb-camera.test:8000",
            },
        }
        for alias in cameras
    }
    if bad_profile:
        devices["unrelated"] = {
            "file": "missing-device-profile.yaml",
            "address": "GPIB0::99::INSTR",
            "simulate": False,
            "backend": {"type": "lamb", "url": "http://lamb-camera.test:8000"},
        }
    path = tmp_path / "bench.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "bench_name": "Camera scoped session test",
                "simulate": False,
                "devices": devices,
                "automation": {
                    "pre_experiment": [f"touch {shlex.quote(str(marker))}"],
                    "post_experiment": [f"touch {shlex.quote(str(marker))}"],
                },
                "experiment": {
                    "title": "Must not start",
                    "description": "camera CLI inspection",
                    "database_path": str(tmp_path / "must-not-exist.sqlite"),
                },
            }
        )
    )
    return path


def _mock_camera_http(monkeypatch, *, discovery_status=200, capture_status=200) -> list[str]:
    paths: list[str] = []
    original_init = httpx.Client.__init__

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.host != "lamb-camera.test" or request.url.port != 8000:
            return httpx.Response(502, text="unexpected test destination")
        if request.url.path == "/webcams":
            if discovery_status != 200:
                return httpx.Response(discovery_status, text="camera discovery failed")
            return httpx.Response(
                200,
                json={
                    "devices": [{"resource_string": "camera-id"}, {"resource_string": "second-id"}]
                },
            )
        if request.url.path in {
            "/webcams/camera-id/capture",
            "/webcams/second-id/capture",
        }:
            if capture_status != 200:
                return httpx.Response(capture_status, text="camera capture failed")
            return httpx.Response(200, content=b"jpeg", headers={"content-type": "image/jpeg"})
        return httpx.Response(404, text=f"unexpected endpoint {request.url.path}")

    def mock_init(self, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", mock_init)
    return paths


@pytest.mark.parametrize("failed_stage", ["discovery", "capture"])
def test_camera_http_errors_are_reported_without_traceback(tmp_path, monkeypatch, failed_stage):
    _mock_camera_http(
        monkeypatch,
        discovery_status=503 if failed_stage == "discovery" else 200,
        capture_status=503 if failed_stage == "capture" else 200,
    )
    path = _bench_yaml(tmp_path)
    result = CliRunner().invoke(
        app, ["camera", "capture", "camera", str(tmp_path / "frame.jpg"), "--bench", str(path)]
    )
    assert result.exit_code == 1
    assert "Error:" in result.stdout
    assert "503" in result.stdout
    assert "Traceback" not in result.output
    assert not (tmp_path / "frame.jpg").exists()


def test_camera_list_and_explicit_info_skip_unrelated_invalid_profile(tmp_path, monkeypatch):
    paths = _mock_camera_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path)
    runner = CliRunner()

    listed = runner.invoke(app, ["camera", "list", "--json", "--bench", str(bench_path)])
    assert listed.exit_code == 0, listed.output
    assert [row["alias"] for row in json.loads(listed.stdout)] == ["camera"]
    assert paths == []

    info = runner.invoke(app, ["camera", "info", "camera", "--json", "--bench", str(bench_path)])
    assert info.exit_code == 0, info.output
    assert json.loads(info.stdout)["alias"] == "camera"
    assert paths == []
    assert not (tmp_path / "automation-ran").exists()
    assert not (tmp_path / "must-not-exist.sqlite").exists()


def test_camera_capture_targets_explicit_alias_and_skips_bad_profile(tmp_path, monkeypatch):
    paths = _mock_camera_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path)
    output = tmp_path / "frame.jpg"

    result = CliRunner().invoke(
        app,
        [
            "camera",
            "capture",
            "camera",
            str(output),
            "--no-metadata",
            "--json",
            "--bench",
            str(bench_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b"jpeg"
    assert paths == ["/webcams", "/webcams/camera-id/capture"]
    assert not (tmp_path / "automation-ran").exists()
    assert not (tmp_path / "must-not-exist.sqlite").exists()


def test_explicit_bad_camera_profile_reports_error(tmp_path):
    bench_path = _bench_yaml(tmp_path)
    result = CliRunner().invoke(
        app,
        ["camera", "info", "unrelated", "--json", "--bench", str(bench_path)],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_camera_auto_selection_keeps_ambiguity_between_valid_cameras(tmp_path, monkeypatch):
    paths = _mock_camera_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path, cameras=("camera", "second"), bad_profile=True)

    result = CliRunner().invoke(app, ["camera", "info", "--json", "--bench", str(bench_path)])

    assert result.exit_code == 1
    assert "More than one camera" in result.output
    assert paths == []


def test_camera_auto_selection_reports_unavailable_profiles_when_none_found(tmp_path, monkeypatch):
    paths = _mock_camera_http(monkeypatch)
    bench_path = _bench_yaml(tmp_path, cameras=(), bad_profile=True)

    result = CliRunner().invoke(app, ["camera", "list", "--json", "--bench", str(bench_path)])

    assert result.exit_code == 1
    assert "no Camera capabilities" in result.output
    assert "unrelated" in result.output
    assert paths == []


def test_camera_capture_rejects_unconfigured_address_before_discovery(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("missing resource must not allocate an HTTP client")

    monkeypatch.setattr(httpx.Client, "__init__", forbidden)
    bench_path = _bench_yaml(tmp_path)
    bench = yaml.safe_load(bench_path.read_text())
    bench["devices"]["camera"].pop("address")
    bench_path.write_text(yaml.safe_dump(bench))

    result = CliRunner().invoke(app, ["camera", "capture", "camera", "--bench", str(bench_path)])

    assert result.exit_code == 1
    assert "requires an explicit nonempty address" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("alias", ["typo", "looks-like-a-file.jpg", "meter"])
def test_camera_capture_rejects_unknown_or_non_camera_alias_before_open(
    tmp_path, monkeypatch, alias
):
    from pytestlab import Bench

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid camera alias must not open the bench or construct a client")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Bench, "open", forbidden)
    monkeypatch.setattr(httpx.Client, "__init__", forbidden)
    bench_path = _bench_yaml(tmp_path, bad_profile=False)
    bench = yaml.safe_load(bench_path.read_text())
    bench["devices"]["meter"] = {"profile": "keysight/34470A", "simulate": True}
    bench_path.write_text(yaml.safe_dump(bench))

    result = CliRunner().invoke(app, ["camera", "capture", alias, "--bench", str(bench_path)])
    assert result.exit_code == 1
    assert alias in result.output
    assert set(tmp_path.iterdir()) == {bench_path}
