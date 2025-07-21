#!/bin/bash

# replay_workflow_example.sh
# Example workflow script for PyTestLab replay functionality with real instruments

set -e  # Exit on any error

echo "PyTestLab Replay Mode Example Workflow - Real Instruments"
echo "========================================================="

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_CONFIG="${SCRIPT_DIR}/real_bench.yaml"
TEST_SCRIPT="${SCRIPT_DIR}/example_measurement.py"
RECORDED_SESSION="${SCRIPT_DIR}/recorded_session.yaml"

echo "Configuration:"
echo "  Bench config: ${BENCH_CONFIG}"
echo "  Test script: ${TEST_SCRIPT}"
echo "  Session file: ${RECORDED_SESSION}"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check if LAMB server is accessible
if command -v curl >/dev/null 2>&1; then
    echo "Testing LAMB server connection..."
    if curl -s --connect-timeout 5 http://lamb-server:8000/health >/dev/null 2>&1; then
        echo "✓ LAMB server is accessible"
    else
        echo "⚠ Warning: LAMB server may not be accessible at http://lamb-server:8000"
        echo "  Make sure LAMB server is running and accessible"
    fi
else
    echo "⚠ curl not available, cannot test LAMB server connection"
fi

# Check if files exist
if [[ -f "${BENCH_CONFIG}" ]]; then
    echo "✓ Bench configuration file exists"
else
    echo "✗ Bench configuration file missing: ${BENCH_CONFIG}"
    exit 1
fi

if [[ -f "${TEST_SCRIPT}" ]]; then
    echo "✓ Test script exists"
else
    echo "✗ Test script missing: ${TEST_SCRIPT}"
    exit 1
fi

echo ""

# Step 1: Record a session with real hardware
echo "Step 1: Recording measurement session with real instruments"
echo "=========================================================="
echo ""
echo "This step will:"
echo "- Connect to real PSU (Keysight EDU36311A) via LAMB"
echo "- Connect to real oscilloscope (Keysight DSOX1204G) via LAMB"
echo "- Execute the measurement script"
echo "- Record all instrument interactions"
echo ""

echo "Command to run:"
echo "  pytestlab replay record ${TEST_SCRIPT} --bench ${BENCH_CONFIG} --output ${RECORDED_SESSION}"
echo ""

read -p "Proceed with recording? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Recording skipped. Creating mock session for demonstration..."
    
    # Create a comprehensive mock recorded session
    cat > "${RECORDED_SESSION}" << 'EOF'
psu:
  profile: keysight/EDU36311A
  log:
  - type: query
    command: "*IDN?"
    response: "Keysight Technologies,EDU36311A,MY12345678,A.02.14.01"
    timestamp: 0.1
  - type: write
    command: "CURR 0.1"
    timestamp: 0.5
  - type: write
    command: "OUTP ON"
    timestamp: 0.6
  - type: write
    command: "VOLT 1.0"
    timestamp: 1.0
  - type: query
    command: "MEAS:VOLT?"
    response: "1.002"
    timestamp: 1.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.095"
    timestamp: 1.6
  - type: write
    command: "VOLT 2.0"
    timestamp: 2.0
  - type: query
    command: "MEAS:VOLT?"
    response: "2.001"
    timestamp: 2.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.098"
    timestamp: 2.6
  - type: write
    command: "VOLT 3.0"
    timestamp: 3.0
  - type: query
    command: "MEAS:VOLT?"
    response: "3.003"
    timestamp: 3.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.097"
    timestamp: 3.6
  - type: write
    command: "VOLT 4.0"
    timestamp: 4.0
  - type: query
    command: "MEAS:VOLT?"
    response: "4.002"
    timestamp: 4.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.096"
    timestamp: 4.6
  - type: write
    command: "VOLT 5.0"
    timestamp: 5.0
  - type: query
    command: "MEAS:VOLT?"
    response: "5.001"
    timestamp: 5.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.099"
    timestamp: 5.6
  - type: write
    command: "VOLT 4.0"
    timestamp: 6.0
  - type: query
    command: "MEAS:VOLT?"
    response: "4.001"
    timestamp: 6.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.097"
    timestamp: 6.6
  - type: write
    command: "VOLT 3.0"
    timestamp: 7.0
  - type: query
    command: "MEAS:VOLT?"
    response: "3.002"
    timestamp: 7.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.098"
    timestamp: 7.6
  - type: write
    command: "VOLT 2.0"
    timestamp: 8.0
  - type: query
    command: "MEAS:VOLT?"
    response: "2.000"
    timestamp: 8.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.096"
    timestamp: 8.6
  - type: write
    command: "VOLT 1.0"
    timestamp: 9.0
  - type: query
    command: "MEAS:VOLT?"
    response: "1.001"
    timestamp: 9.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.095"
    timestamp: 9.6
  - type: write
    command: "VOLT 0.0"
    timestamp: 10.0
  - type: query
    command: "MEAS:VOLT?"
    response: "0.001"
    timestamp: 10.5
  - type: query
    command: "MEAS:CURR?"
    response: "0.000"
    timestamp: 10.6
  - type: write
    command: "OUTP OFF"
    timestamp: 11.0
  - type: write
    command: "VOLT 0.0"
    timestamp: 11.1

osc:
  profile: keysight/DSOX1204G
  log:
  - type: query
    command: "*IDN?"
    response: "Keysight Technologies,DSOX1204G,MY87654321,01.40.2017061300"
    timestamp: 0.2
  - type: write
    command: "TIM:SCAL 0.001"
    timestamp: 0.7
  - type: write
    command: "TIM:POS 0.0"
    timestamp: 0.8
  - type: write
    command: "CHAN1:SCAL 1.0"
    timestamp: 0.9
  - type: write
    command: "CHAN1:OFFS 0.0"
    timestamp: 1.0
  - type: write
    command: "CHAN1:COUP DC"
    timestamp: 1.1
  - type: write
    command: "CHAN1:DISP ON"
    timestamp: 1.2
  - type: write
    command: "TRIG:SOUR CHAN1"
    timestamp: 1.3
  - type: write
    command: "TRIG:LEV 2.5"
    timestamp: 1.4
  - type: write
    command: "TRIG:MODE EDGE"
    timestamp: 1.5
  - type: write
    command: "SING"
    timestamp: 1.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "1.985"
    timestamp: 2.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "1.001"
    timestamp: 2.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-0.984"
    timestamp: 2.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 2.4
  - type: write
    command: "SING"
    timestamp: 2.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "3.970"
    timestamp: 3.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "2.002"
    timestamp: 3.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-1.968"
    timestamp: 3.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 3.4
  - type: write
    command: "SING"
    timestamp: 3.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "5.955"
    timestamp: 4.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "3.003"
    timestamp: 4.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-2.952"
    timestamp: 4.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 4.4
  - type: write
    command: "SING"
    timestamp: 4.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "7.940"
    timestamp: 5.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "4.002"
    timestamp: 5.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-3.938"
    timestamp: 5.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 5.4
  - type: write
    command: "SING"
    timestamp: 5.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "9.925"
    timestamp: 6.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "5.001"
    timestamp: 6.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-4.924"
    timestamp: 6.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 6.4
  - type: write
    command: "SING"
    timestamp: 6.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "7.941"
    timestamp: 7.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "4.001"
    timestamp: 7.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-3.940"
    timestamp: 7.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 7.4
  - type: write
    command: "SING"
    timestamp: 7.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "5.956"
    timestamp: 8.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "3.002"
    timestamp: 8.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-2.954"
    timestamp: 8.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 8.4
  - type: write
    command: "SING"
    timestamp: 8.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "3.971"
    timestamp: 9.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "2.001"
    timestamp: 9.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-1.970"
    timestamp: 9.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 9.4
  - type: write
    command: "SING"
    timestamp: 9.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "1.986"
    timestamp: 10.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "1.001"
    timestamp: 10.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-0.985"
    timestamp: 10.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "1000.0"
    timestamp: 10.4
  - type: write
    command: "SING"
    timestamp: 10.8
  - type: query
    command: "MEAS:VPP? CHAN1"
    response: "0.002"
    timestamp: 11.1
  - type: query
    command: "MEAS:VMAX? CHAN1"
    response: "0.001"
    timestamp: 11.2
  - type: query
    command: "MEAS:VMIN? CHAN1"
    response: "-0.001"
    timestamp: 11.3
  - type: query
    command: "MEAS:FREQ? CHAN1"
    response: "0.0"
    timestamp: 11.4
EOF

    echo "✓ Mock session file created for demonstration"
else
    echo "Recording with real instruments..."
    echo "Command: pytestlab replay record ${TEST_SCRIPT} --bench ${BENCH_CONFIG} --output ${RECORDED_SESSION}"
    # Note: The actual recording would be done here
    echo "⚠ Actual recording requires real hardware setup"
fi

echo ""

# Step 2: Replay the session
echo "Step 2: Replaying measurement session"
echo "====================================="
echo ""
echo "This step will:"
echo "- Load the recorded session data"
echo "- Create replay backends for each instrument"
echo "- Execute the same measurement script in replay mode"
echo "- Verify exact command sequence matching"
echo ""

if [[ -f "${RECORDED_SESSION}" ]]; then
    echo "✓ Session file found: ${RECORDED_SESSION}"
    echo ""
    echo "Command to run replay:"
    echo "  pytestlab replay run ${TEST_SCRIPT} --session ${RECORDED_SESSION}"
    echo ""
    
    read -p "Execute replay now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Running replay..."
        # pytestlab replay run "${TEST_SCRIPT}" --session "${RECORDED_SESSION}"
        echo "⚠ Replay command would execute here"
        echo "  (Commented out for demo - uncomment to run actual replay)"
    else
        echo "Replay skipped"
    fi
else
    echo "✗ Session file not found: ${RECORDED_SESSION}"
fi

echo ""

# Step 3: Demonstrate validation scenarios
echo "Step 3: Validation and Error Detection"
echo "======================================"
echo ""
echo "The replay system provides strict validation:"
echo ""
echo "✓ Command Sequence Validation:"
echo "  - Every command must match exactly"
echo "  - Commands must be in the correct order"
echo "  - All parameters must match recorded values"
echo ""
echo "✓ Instrument State Tracking:"
echo "  - Each instrument's command log is independent"
echo "  - Concurrent instrument operations are supported"
echo "  - Timing information is preserved"
echo ""
echo "✓ Error Detection Examples:"
echo "  - Wrong voltage value: ReplayMismatchError"
echo "  - Missing command: ReplayMismatchError"
echo "  - Extra command: ReplayMismatchError"
echo "  - Wrong instrument order: ReplayMismatchError"
echo ""

# Step 4: Advanced usage examples
echo "Step 4: Advanced Usage Examples"
echo "==============================="
echo ""
echo "Regression Testing:"
echo "  1. Record a known-good measurement sequence"
echo "  2. Replay during development to catch changes"
echo "  3. Use in CI/CD pipelines for automated testing"
echo ""
echo "Documentation and Training:"
echo "  1. Record complex measurement procedures"
echo "  2. Replay for training without real hardware"
echo "  3. Create reproducible measurement examples"
echo ""
echo "Debugging and Analysis:"
echo "  1. Record problematic sequences for analysis"
echo "  2. Replay to isolate specific command issues"
echo "  3. Compare different software versions"
echo ""

# Step 5: Summary and next steps
echo "Step 5: Summary and Next Steps"
echo "=============================="
echo ""
echo "Files created:"
echo "  📄 ${BENCH_CONFIG} - Real instrument bench configuration"
echo "  🐍 ${TEST_SCRIPT} - Comprehensive measurement script"
echo "  📊 ${RECORDED_SESSION} - Recorded session data"
echo ""
echo "Key commands:"
echo "  📹 Record: pytestlab replay record ${TEST_SCRIPT} --bench ${BENCH_CONFIG} --output ${RECORDED_SESSION}"
echo "  ▶️  Replay:  pytestlab replay run ${TEST_SCRIPT} --session ${RECORDED_SESSION}"
echo ""
echo "Requirements for real hardware testing:"
echo "  🔌 LAMB server running and accessible"
echo "  🔋 Keysight EDU36311A power supply connected"
echo "  📺 Keysight DSOX1204G oscilloscope connected"
echo "  🌐 Network connectivity to instruments"
echo ""
echo "Safety features included:"
echo "  ⚡ Voltage and current limits in bench config"
echo "  🛡️  Automatic output disable on script completion"
echo "  🚨 Emergency stop capabilities"
echo "  📏 Parameter validation"
echo ""

echo "Workflow setup complete!"
echo ""
echo "To test with real instruments:"
echo "  1. Ensure LAMB server is running"
echo "  2. Connect and configure instruments"
echo "  3. Run the recording command"
echo "  4. Execute replay for validation"
echo ""
echo "To test without hardware:"
echo "  1. Use the provided mock session file"
echo "  2. Run replay with mock data"
echo "  3. Modify script to see mismatch detection"
