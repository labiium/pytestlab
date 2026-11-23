"""Mirror install: platform detection, checksum verification, and extraction
into ~/.pytestlab/ngspice (the path the lane auto-discovers)."""

from __future__ import annotations

import hashlib
import io
import platform
import tarfile
from pathlib import Path

import pytest

from pytestlab.sim.circuit import _mirror
from pytestlab.sim.circuit.spice import managed_ngspice_path
from pytestlab.sim.circuit.spice import resolve_ngspice


def test_mirror_asset_detects_arm(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    assert _mirror.mirror_asset() == "linux-aarch64"
    monkeypatch.setattr(platform, "machine", lambda: "armv7l")
    assert _mirror.mirror_asset() == "linux-armv7"


def test_mirror_asset_none_for_non_arm(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert _mirror.mirror_asset() is None
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert _mirror.mirror_asset() is None


def _fake_bundle() -> bytes:
    """A minimal valid bundle: ngspice/bin/ngspice inside a .tar.gz."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("ngspice/bin/ngspice")
        payload = b"#!/bin/sh\necho fake-ngspice\n"
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _patch_downloads(monkeypatch, data: bytes, sha: str):
    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(data)

    class FakeResp:
        def __init__(self, text: str):
            self._t = text.encode()

        def read(self):
            return self._t

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(_mirror.urllib.request, "urlretrieve", fake_urlretrieve)
    monkeypatch.setattr(
        _mirror.urllib.request,
        "urlopen",
        lambda url, timeout=0: FakeResp(f"{sha}  ngspice-linux-aarch64.tar.gz"),
    )


def test_install_from_mirror_verifies_and_extracts(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    data = _fake_bundle()
    _patch_downloads(monkeypatch, data, hashlib.sha256(data).hexdigest())

    path = _mirror.install_from_mirror("linux-aarch64", log=lambda m: None)

    assert path == managed_ngspice_path()
    assert path.exists()
    # And the lane resolves to it when nothing is on PATH.
    assert resolve_ngspice("ngspice-not-on-path-xyz") == str(path)


def test_install_from_mirror_rejects_bad_checksum(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    data = _fake_bundle()
    _patch_downloads(monkeypatch, data, "deadbeef" * 8)  # wrong digest

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _mirror.install_from_mirror("linux-aarch64", log=lambda m: None)
    assert not managed_ngspice_path().exists()
