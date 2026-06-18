from __future__ import annotations

import os
from pathlib import Path

import pytest

from pytestlab.hardware.lamb_scope import run_lamb_scope_checks

pytestmark = pytest.mark.requires_real_hw


def test_remote_lamb_scope_acceptance_harness(tmp_path: Path):
    if os.getenv("PYTESTLAB_RUN_REMOTE_LAMB") != "1":
        pytest.skip("set PYTESTLAB_RUN_REMOTE_LAMB=1 to run remote LAMB hardware checks")
    lamb_url = os.getenv("PYTESTLAB_LAMB_URL") or os.getenv("LAMB_SERVER")
    if not lamb_url:
        pytest.skip("set PYTESTLAB_LAMB_URL or LAMB_SERVER to run remote LAMB hardware checks")

    report = run_lamb_scope_checks(
        url=lamb_url,
        timeout_ms=int(os.getenv("PYTESTLAB_LAMB_TIMEOUT_MS", "5000")),
        capture_waveform=os.getenv("PYTESTLAB_LAMB_CAPTURE_WAVEFORM") == "1",
        strict=os.getenv("PYTESTLAB_LAMB_STRICT", "0") == "1",
        output_dir=tmp_path,
    )

    assert any(row.model == "MXR404A" for row in report.rows)
    assert any(row.model == "HD304MSO" for row in report.rows)
    assert any(row.check == "active_resource_preflight" for row in report.rows)
    assert report.artifact_path is not None
