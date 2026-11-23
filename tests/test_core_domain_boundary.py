"""Generic bench APIs must not depend on wafer geometry or alignment."""

import pytest

from pytestlab import Bench
from pytestlab.config.bench_config import BenchConfigExtended


def test_core_bench_has_no_wafer_workflow_methods():
    assert not hasattr(Bench, "register_dut")
    assert not hasattr(Bench, "align")
    assert not hasattr(Bench, "dut")


def test_camera_bench_rejects_domain_configuration():
    data = {
        "bench_name": "camera",
        "devices": {"camera": {"device_type": "camera", "backend": {"type": "lamb"}}},
    }
    BenchConfigExtended.model_validate(data)
    with pytest.raises(ValueError):
        BenchConfigExtended.model_validate({**data, "alignment": {}})
