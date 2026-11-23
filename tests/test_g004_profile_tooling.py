from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GALLERY_SCRIPT = PROJECT_ROOT / "scripts" / "generate_profile_gallery.py"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "scripts" / "bootstrap_from_pymeasure.py"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pymeasure_driver(path: Path, *, command: str = "*IDN?") -> None:
    path.write_text(
        "\n".join(
            [
                "from pymeasure.instruments import Instrument",
                "",
                "class GoodMeter(Instrument):",
                f"    voltage = Instrument.measurement({command!r}, 'Read voltage')",
                "",
            ]
        )
    )


def test_entry_point_failures_are_recorded_and_logged(monkeypatch, caplog):
    from pytestlab.devices import registry

    class BrokenEntryPoint:
        name = "broken_backend"

        def load(self):
            raise RuntimeError("boom")

    def fake_entry_points(*, group: str):
        assert group in {
            "pytestlab.device_drivers",
            "pytestlab.device_configs",
            "pytestlab.backends",
        }
        return [BrokenEntryPoint()] if group == "pytestlab.backends" else []

    monkeypatch.setattr(registry.metadata, "entry_points", fake_entry_points)
    monkeypatch.setattr(registry, "_entry_points_loaded", False)
    registry.clear_entry_point_diagnostics()

    with caplog.at_level(logging.WARNING, logger="pytestlab.devices.registry"):
        registry.load_entry_points()

    diagnostics = registry.get_entry_point_diagnostics()
    assert diagnostics == [
        {
            "group": "pytestlab.backends",
            "kind": "backend",
            "name": "broken_backend",
            "error_type": "RuntimeError",
            "message": "boom",
        }
    ]
    assert "broken_backend" in caplog.text
    assert "boom" in caplog.text


def test_gallery_reports_all_invalid_profiles_and_preserves_destination(tmp_path, capsys):
    gallery = _load_module(GALLERY_SCRIPT, "generate_profile_gallery_under_test")
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    dest = tmp_path / "gallery.md"
    dest.write_text("existing gallery")

    good = profiles_dir / "good.yaml"
    good.write_text(
        yaml.safe_dump({"manufacturer": "Acme", "model": "M1", "device_type": "multimeter"})
    )
    bad_yaml = profiles_dir / "bad-yaml.yaml"
    bad_yaml.write_text("manufacturer: [unterminated")
    bad_shape = profiles_dir / "bad-shape.yaml"
    bad_shape.write_text("- not\n- a\n- mapping\n")

    status = gallery.generate_profile_gallery(profiles_dir=profiles_dir, dest_path=dest)

    output = capsys.readouterr()
    assert status == 1
    assert "bad-yaml.yaml" in output.err
    assert "bad-shape.yaml" in output.err
    assert "2 profile(s) failed" in output.err
    assert dest.read_text() == "existing gallery"


def test_gallery_cli_exits_nonzero_without_replacing_destination(tmp_path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    dest = tmp_path / "gallery.md"
    dest.write_text("old")
    (profiles_dir / "invalid.yaml").write_text(": bad")

    result = subprocess.run(
        [
            sys.executable,
            str(GALLERY_SCRIPT),
            "--profiles-dir",
            str(profiles_dir),
            "--dest",
            str(dest),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "invalid.yaml" in result.stderr
    assert dest.read_text() == "old"


def test_pymeasure_batch_strict_reports_every_failure_and_exits_nonzero(tmp_path):
    source = tmp_path / "drivers"
    source.mkdir()
    _write_pymeasure_driver(source / "good.py")
    (source / "bad_syntax.py").write_text("def nope(:\n")
    nested = source / "nested"
    nested.mkdir()
    (nested / "bad_encoding.py").write_bytes(b"\xff\xfe\x00")

    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            str(source),
            "--batch-out-dir",
            str(out_dir),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "bad_syntax.py" in combined
    assert "nested/bad_encoding.py" in combined
    assert "2 failed" in combined
    assert (out_dir / "good.yaml").exists()


def test_pymeasure_batch_best_effort_exits_zero_with_failure_summary(tmp_path):
    source = tmp_path / "drivers"
    source.mkdir()
    _write_pymeasure_driver(source / "good.py")
    (source / "bad_syntax.py").write_text("class Broken(:\n")

    out_dir = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            str(source),
            "--batch-out-dir",
            str(out_dir),
            "--best-effort",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "bad_syntax.py" in combined
    assert "1 failed" in combined
    assert (out_dir / "good.yaml").exists()


def test_pymeasure_single_file_error_propagates(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def nope(:\n")

    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP_SCRIPT), str(bad)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SyntaxError" in result.stderr
