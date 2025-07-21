# Record & Replay Mode

PyTestLab's **Record & Replay** system enables you to capture real instrument interactions and replay them with exact sequence validation. This powerful feature supports reproducible measurements, offline development, and regression testing.

## Overview

The replay system consists of two main backends:

- **`SessionRecordingBackend`** - Wraps real instrument backends to record all interactions
- **`ReplayBackend`** - Replays recorded sessions with strict sequence validation

## Core Benefits

### 🎯 Reproducible Measurements
Execute the exact same SCPI command sequences every time, ensuring consistent results across different runs and environments.

### 🛡️ Measurement Integrity  
Scripts cannot deviate from validated sequences. Any attempt to execute different commands triggers immediate error detection.

### 🔬 Offline Analysis
Run complex measurement procedures without requiring physical instruments, perfect for development and demonstration.

### 🧪 Regression Testing
Validate that measurement procedures remain unchanged over time. Catch unintended script modifications immediately.

## How It Works

### Recording Phase
1. The `SessionRecordingBackend` wraps your actual instrument backends (VISA, LAMB, etc.)
2. All commands, responses, and timestamps are logged to a structured YAML file
3. Your script runs normally against real instruments while being recorded

### Replay Phase  
1. The `ReplayBackend` loads the recorded session file
2. Your script runs against the replay backend instead of real instruments
3. Each command is validated against the recorded sequence
4. Recorded responses are returned exactly as they were captured
5. Any deviation from the sequence triggers a `ReplayMismatchError`

## Basic Usage

### Command Line Interface

The simplest way to use replay mode is through the CLI:

```bash
# Record a measurement session
pytestlab replay record my_measurement.py --bench bench.yaml --output session.yaml

# Replay the recorded session
pytestlab replay run my_measurement.py --session session.yaml
```

### Programmatic Usage

You can also use replay mode programmatically:

```python
import asyncio
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments.backends import ReplayBackend, SessionRecordingBackend
from pytestlab.instruments.backends.visa import VisaBackend

async def record_session():
    # Create real backend
    real_backend = VisaBackend("TCPIP0::192.168.1.100::inst0::INSTR")
    
    # Wrap with recording backend
    recording_backend = SessionRecordingBackend(real_backend, "session.yaml")
    
    # Create instrument with recording backend
    psu = AutoInstrument.from_config(
        "keysight/EDU36311A",
        backend_override=recording_backend
    )
    
    await psu.connect_backend()
    
    # Perform measurements (will be recorded)
    await psu.set_voltage(1, 5.0)
    voltage = await psu.read_voltage(1)
    print(f"Recorded voltage: {voltage}")
    
    await psu.close()

async def replay_session():
    # Create replay backend
    replay_backend = ReplayBackend("session.yaml")
    
    # Create instrument with replay backend
    psu = AutoInstrument.from_config(
        "keysight/EDU36311A",
        backend_override=replay_backend
    )
    
    await psu.connect_backend()
    
    # This will replay the exact recorded sequence
    await psu.set_voltage(1, 5.0)  # Must match recorded command
    voltage = await psu.read_voltage(1)  # Returns recorded response
    print(f"Replayed voltage: {voltage}")
    
    await psu.close()

# Record first, then replay
asyncio.run(record_session())
asyncio.run(replay_session())
```

## Session File Format

Session files are stored in YAML format with a clear structure:

```yaml
instrument_key:
  profile: profile/name  
  log:
  - type: query|write
    command: "SCPI command"
    response: "instrument response"  # only for queries
    timestamp: 1234567890.123456
```

### Example Session File

```yaml
psu:
  profile: keysight/EDU36311A
  log:
  - type: query
    command: '*IDN?'
    response: 'Keysight Technologies,EDU36311A,CN61130056,K-01.08.03-01.00-01.08-02.00'
    timestamp: 0.029241038020700216
  - type: write
    command: 'CURR 0.1, (@1)'
    timestamp: 0.7136540680075996
  - type: write
    command: 'OUTP:STAT ON, (@1)'
    timestamp: 0.7608416990260594
  - type: write
    command: 'VOLT 5.0, (@1)'
    timestamp: 0.8096857140189968
  - type: query
    command: 'MEAS:VOLT? (@1)'
    response: '+4.99918100E+00'
    timestamp: 1.614894539990928

oscilloscope:
  profile: keysight/DSOX1204G
  log:
  - type: query
    command: '*IDN?'
    response: 'KEYSIGHT TECHNOLOGIES,DSOX1204G,CN63197144,02.12.2021071625'
    timestamp: 0.08468247798737139
  - type: write
    command: ':TIMebase:SCALe 0.001'
    timestamp: 0.11525928595801815
  - type: query
    command: 'MEAS:VPP? CHAN1'
    response: '+280E-03'
    timestamp: 1.4958587769651785
```

## Error Detection and Validation

### Command Sequence Validation

The replay backend enforces strict command sequence validation:

```python
# During recording
await psu.set_voltage(1, 5.0)  # Records: "VOLT 5.0, (@1)"
await psu.set_current(1, 0.1)  # Records: "CURR 0.1, (@1)"

# During replay - this works
await psu.set_voltage(1, 5.0)  # ✓ Matches recorded sequence
await psu.set_current(1, 0.1)  # ✓ Matches recorded sequence

# During replay - this fails  
await psu.set_voltage(1, 3.0)  # ✗ ReplayMismatchError!
```

### ReplayMismatchError

When a command doesn't match the recorded sequence:

```python
from pytestlab.instruments.backends.errors import ReplayMismatchError

try:
    await psu.set_voltage(1, 3.0)  # Expected 5.0 in recording
except ReplayMismatchError as e:
    print(f"Sequence mismatch: {e}")
    # Output: Expected command 'VOLT 5.0, (@1)' but got 'VOLT 3.0, (@1)'
```

## Advanced Features

### Multi-Instrument Sessions

Record and replay multiple instruments simultaneously:

```yaml
# bench.yaml
instruments:
  psu:
    profile: "keysight/EDU36311A"
    address: "TCPIP0::192.168.1.100::inst0::INSTR"
  oscilloscope:
    profile: "keysight/DSOX1204G" 
    address: "TCPIP0::192.168.1.101::inst0::INSTR"
  dmm:
    profile: "keysight/34470A"
    address: "USB0::0x0957::0x1B07::MY56430012::INSTR"
```

```bash
# Records all three instruments
pytestlab replay record multi_instrument_test.py --bench bench.yaml --output session.yaml
```

### Timestamp Analysis

Session files include precise timestamps for performance analysis:

```python
import yaml

with open("session.yaml") as f:
    session = yaml.safe_load(f)

# Analyze command timing
for entry in session["psu"]["log"]:
    print(f"{entry['timestamp']:.6f}: {entry['command']}")
```

### Backend Compatibility

The replay system works with all PyTestLab backends:

- **VISA Backend** - Traditional SCPI over VISA
- **LAMB Backend** - Network-based instrument control  
- **Simulation Backend** - Can record simulation results for testing
- **Custom Backends** - Any `AsyncInstrumentIO` implementation

### Integration with Bench System

Replay mode integrates seamlessly with PyTestLab's bench system:

```python
async def measurement_with_bench():
    # Using bench descriptor
    async with await pytestlab.Bench.open("bench.yaml") as bench:
        # All instruments are automatically wrapped for recording
        psu_voltage = await bench.psu.read_voltage(1)
        osc_measurement = await bench.oscilloscope.measure_vpp(1)
        dmm_reading = await bench.dmm.measure_voltage_dc()
        
        return {
            'psu': psu_voltage,
            'osc': osc_measurement, 
            'dmm': dmm_reading
        }
```

## Best Practices

### 1. Record with Real Instruments
Always record sessions using actual hardware to capture realistic instrument responses and timing.

### 2. Validate Recordings
Review session files after recording to ensure they captured the expected sequence:

```bash
# Check recorded commands
grep "command:" session.yaml | head -10
```

### 3. Version Control Sessions
Include session files in version control to track changes in measurement procedures.

### 4. Use Descriptive Names
Use meaningful names for session files:

```bash
pytestlab replay record power_supply_characterization.py --output psu_char_v1.2.yaml
```

### 5. Handle Errors Gracefully
Always include proper error handling in replay scripts:

```python
from pytestlab.instruments.backends.errors import ReplayMismatchError

try:
    await run_measurement()
except ReplayMismatchError as e:
    logger.error(f"Measurement sequence changed: {e}")
    raise
```

## Troubleshooting

### Common Issues

**Problem**: `ReplayMismatchError` on first command  
**Solution**: Ensure you're using the same instrument profile during replay as during recording.

**Problem**: Session file not found  
**Solution**: Check file paths and ensure session files are in the expected location.

**Problem**: Unexpected command sequence  
**Solution**: Review the session file to understand the recorded sequence and ensure your script matches exactly.

### Debugging Tips

1. **Enable verbose logging** to see detailed command matching:
```python
import logging
logging.getLogger('pytestlab.instruments.backends.replay').setLevel(logging.DEBUG)
```

2. **Compare session files** when troubleshooting sequence mismatches:
```bash
diff -u expected_session.yaml actual_session.yaml
```

3. **Use smaller test scripts** to isolate problematic command sequences.

## Examples

Complete working examples are available in the `examples/replay_mode/` directory:

- `basic_recording.py` - Simple PSU recording example
- `multi_instrument_session.py` - Complex measurement with multiple instruments  
- `replay_validation.py` - Demonstration of error detection
- `cli_workflow_demo.sh` - Complete CLI workflow example

## API Reference

For detailed API documentation, see:

- [`ReplayBackend`](../api/backends.md#replaybackend)
- [`SessionRecordingBackend`](../api/backends.md#sessionrecordingbackend) 
- [`ReplayMismatchError`](../api/errors.md#replaymismatcherror)
