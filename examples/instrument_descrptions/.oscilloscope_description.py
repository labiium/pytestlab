oscilloscope_description = {
    "manufacturer": "XYZ Corp.",    # Manufacturer name
    "model": "ABC1000",             # Model name/number
    "channels": {
        1: {
            "description": "Input Channel 1",
            "min": -5.0,             # Minimum voltage (in volts) supported on Channel 1
            "max": 5.0,              # Maximum voltage (in volts) supported on Channel 1
            "input_coupling": ["AC", "DC", "GND"],   # List of supported input coupling modes
            "input_impedance": 1e6,   # Input impedance (in ohms) for Channel 1
            "probe_attenuation": [1, 10, 100],       # List of supported probe attenuation ratios
            # Add more channel-specific settings and limitations as needed
        },
        2: {
            "description": "Input Channel 2",
            "min": -5.0,             # Minimum voltage (in volts) supported on Channel 2
            "max": 5.0,              # Maximum voltage (in volts) supported on Channel 2
            "input_coupling": ["AC", "DC", "GND"],   # List of supported input coupling modes
            "input_impedance": 1e6,   # Input impedance (in ohms) for Channel 2
            "probe_attenuation": [1, 10, 100],       # List of supported probe attenuation ratios
            # Add more channel-specific settings and limitations as needed
        },
    },
    "timebase": {
        "min_scale": 1e-9,         # Minimum timebase scale (in seconds) supported
        "max_scale": 10.0,         # Maximum timebase scale (in seconds) supported
        "time_units": ["s", "ms", "us", "ns"],   # List of supported time units
        # Add more timebase-related settings and limitations as needed
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "VIDEO", "USB", "RS232"],   # List of supported trigger modes
        "slope": ["RISING", "FALLING"],          # List of supported trigger slope options
        "external_trigger_input": ["EXT", "EXT/10", "EXT/100"],  # List of supported external trigger inputs
        # Add more trigger-related settings and limitations as needed
    },
    "bandwidth": "0.5 - 6 GHz",            # Oscilloscope bandwidth (in Hz)
    "analog_channels": [4, 8],             # Number of analog channels supported (upgradeable)
    "sampling_rate": "16 GSa/s",           # Oscilloscope sampling rate (in samples per second)
    "standard_memory": "200Mpts/ch",       # Standard memory per channel (in points)
    "waveform_update_rate": ">200,000 wfms/sec",  # Waveform update rate (in waveforms per second)
    # Add more settings and limitations as needed
}
