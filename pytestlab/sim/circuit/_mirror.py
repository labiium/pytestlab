"""Fetch a prebuilt ngspice bundle from the labiium/ngspice_mirror releases.

Used for platforms that have no upstream/conda-forge ngspice and no usable
package manager (Linux arm64/armv7). The bundle is relocatable and installs
into ~/.pytestlab/ngspice/ with no system package manager or root.
"""
from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .spice import managed_ngspice_path

_MIRROR_BASE = "https://github.com/labiium/ngspice_mirror/releases/latest/download"


def mirror_asset() -> str | None:
    """Return the mirror asset tag for this platform, or None if not covered."""
    if platform.system().lower() != "linux":
        return None
    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64"):
        return "linux-aarch64"
    if machine in ("armv7l", "armv7", "armhf") or machine.startswith("armv7"):
        return "linux-armv7"
    return None


def install_from_mirror(
    asset: str, *, log: Callable[[str], None] = print, timeout: float = 180.0
) -> Path:
    """Download, checksum-verify, and extract the mirror bundle for ``asset``.

    Returns the path to the installed ngspice binary. Raises on any failure
    (network, checksum mismatch, missing binary after extraction).
    """
    url = f"{_MIRROR_BASE}/ngspice-{asset}.tar.gz"
    sha_url = f"{url}.sha256"
    dest_root = Path.home() / ".pytestlab"
    dest_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tarball = Path(td) / "ngspice.tar.gz"
        log(f"Downloading {url}")
        urllib.request.urlretrieve(url, tarball)  # noqa: S310 - pinned https URL

        with urllib.request.urlopen(sha_url, timeout=timeout) as resp:  # noqa: S310
            expected = resp.read().decode().split()[0].strip()
        actual = hashlib.sha256(tarball.read_bytes()).hexdigest()
        if expected != actual:
            raise RuntimeError(
                f"checksum mismatch for {asset}: expected {expected}, got {actual}"
            )
        log("Checksum verified.")

        target = dest_root / "ngspice"
        if target.exists():
            shutil.rmtree(target)
        with tarfile.open(tarball) as tf:
            # The bundle has a top-level "ngspice/" dir; extract into ~/.pytestlab.
            try:
                tf.extractall(dest_root, filter="data")  # py3.12+
            except TypeError:
                tf.extractall(dest_root)  # noqa: S202 - our own pinned, checksummed artifact

    binary = managed_ngspice_path()
    if not binary.exists():
        raise RuntimeError("bundle extracted but ngspice binary not found")
    binary.chmod(0o755)
    return binary
