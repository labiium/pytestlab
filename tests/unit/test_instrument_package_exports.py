import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", ["public", "submodule", "factory"])
def test_class_exports_are_stable_regardless_of_import_order(first):
    code = """
import importlib
import sys

names = (
    "AutoInstrument", "DCActiveLoad", "Multimeter", "Oscilloscope",
    "PowerSupply", "SourceMeasure", "WaveformGenerator",
)
package = importlib.import_module("pytestlab.instruments")
if sys.argv[1] == "public":
    for name in names:
        assert isinstance(getattr(package, name), type)
elif sys.argv[1] == "submodule":
    for name in names:
        importlib.import_module(f"{package.__name__}.{name}")
else:
    from pytestlab import AutoInstrument, SourceMeasure
    AutoInstrument.from_preset("keysight/34470A")
    AutoInstrument.from_preset("keysight/DSOX1204G")
    assert isinstance(SourceMeasure, type)

for name in names:
    module = importlib.import_module(f"{package.__name__}.{name}")
    namespace = {}
    exec(f"from pytestlab.instruments import {name}", namespace)
    assert namespace[name] is getattr(module, name)
    assert isinstance(namespace[name], type)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, first], capture_output=True, text=True, env=os.environ.copy()
    )
    assert result.returncode == 0, result.stderr
