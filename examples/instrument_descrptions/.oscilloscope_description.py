oscilloscope_description = {
    "manufacturer": "Keysight",    # Manufacturer name
    "model": "Magic Oscilloscope with 2 Channels",    # Model name/number
    "device_type": "oscilloscope", # Device type
    "visa_resource": "USB0::0x0957::0x1799::MY58100838::INSTR",   # VISA resource string
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
    # Jitter analysis
    "jitter_analysis": {
        "available_types": ["RMS", "Peak-to-Peak"],   # Types of jitter measurement
        "jitter_sources": ["Time Interval Error", "Phase Noise"], # List of selectable jitter sources
        "analysis_depth": 1e6,         # Maximum number of cycles or edges that can be analyzed
        "histogram_bins": 256,         # Number of histogram bins for jitter distribution
        "modulation_analysis": True,   # Supports modulation analysis or not
        "real_time_analysis": True,    # Supports real-time jitter analysis or not
        "min_jitter_measurement": 1e-12,   # Minimum measurable jitter (in seconds)
        "max_jitter_measurement": 1e-3,    # Maximum measurable jitter (in seconds)
        # Add more jitter-related settings and limitations as needed
    }
    # Add more settings and limitations as needed
}
