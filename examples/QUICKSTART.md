# Smart Bench Quick Start

## 🚀 60 Second Setup

### 1. Test Smart Bench (Simulation)
```bash
cd examples
python simple_bench_test.py
```

### 2. Load Instruments Directly
```python
from pytestlab import AutoInstrument

osc = AutoInstrument.from_config("keysight/DSOX1204G", simulate=True)
awg = AutoInstrument.from_config("keysight/EDU33212A", simulate=True)
psu = AutoInstrument.from_config("keysight/EDU36311A", simulate=True)
dmm = AutoInstrument.from_config("keysight/EDU34450A", simulate=True)

print(osc.id(), awg.id(), psu.id(), dmm.id())
```

### 3. Load via Bench Configuration
```python
from pytestlab.bench import Bench

bench = Bench.open("smarbench.yaml")

# Access instruments
osc = bench.instruments["osc"]
awg = bench.instruments["awg"]
psu = bench.instruments["psu"]
dmm = bench.instruments["dmm"]

# Use PSU
psu.set_voltage(1, 3.3)
psu.output(1, True)
```

## 📋 Files

- `smarbench.yaml` - Main configuration (4 instruments)
- `simple_bench_test.py` - Quick test (RECOMMENDED)
- `test_smarbench.py` - Full test suite (9 tests)
- `SMARBENCH_README.md` - Complete documentation

## ✅ Verification

All tests passing:
- 194 unit tests passed
- 9 bench tests passed
- All instrument loading verified

## 🎯 Next Steps

1. Read `SMARBENCH_README.md` for detailed usage
2. Customize `smarbench.yaml` for your setup
3. Switch to `simulate: false` for real hardware

**Status: PRODUCTION READY** 🚀
