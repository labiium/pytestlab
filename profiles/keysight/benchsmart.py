oscilloscope_profile = {
    "DSOX1204A":{
    "manufacturer": "Keysight",
    "model": "DSOX1204A",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Analog Channel 1",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"], 
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        2: {
        "description": "Analog Channel 2",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        3: {
        "description": "Analog Channel 3",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        4: {
        "description": "Analog Channel 4",
        "min": -5,
        "max": 5, 
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        }
    },
    "bandwidth": 70e6,
    "sampling_rate": 2e9,
    "memory": 2e6,
    "waveform_update_rate": 2e5,
    "trigger_modes": ["Edge", "Pulse Width", "Video", "I2C", "SPI", "UART/RS232", "CAN", "LIN"],
    "timebase": {  
        "min": 5e-9,
        "max": 50
    }
    },
    "DSOX1204G": {
    "manufacturer": "Keysight",
    "model": "DSOX1204G", 
    "device_type": "Oscilloscope",
    "channels": {
        1: {
        "description": "Analog Channel 1",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        2: {
        "description": "Analog Channel 2",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        3: {
        "description": "Analog Channel 3",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        },
        4: {
        "description": "Analog Channel 4",
        "min": -5,
        "max": 5,
        "input_coupling": ["DC", "AC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10]
        }
    },
    "bandwidth": 70e6,
    "sampling_rate": 2e9,
    "memory": 2e6,
    "waveform_update_rate": 2e5,
    "trigger_modes": ["Edge", "Pulse Width", "Video", "I2C", "SPI", "UART/RS232", "CAN", "LIN"],
    "timebase": {
        "min": 5e-9,
        "max": 50
    },
    "function_generator": {
        "waveform_types": ["Sine", "Square", "Ramp", "Pulse", "Noise", "DC"],
        "frequency": {
        "min": 0.1,
        "max": 20e6
        },
        "amplitude": {
        "min": 2e-3,
        "max": 20    
        }
    }
    }
}

power_supply_profile = {
  "EDU36311A": {
    "manufacturer": "Keysight", 
    "model": "EDU36311A",
    "device_type": "powersupply",
    
    "outputs": {
      1: {
        "voltage": {
          "min": 0,
          "max": 6
        },
        "current": {
          "min": 0, 
          "max": 5
        }
      },
      2: {
        "voltage": {
          "min": 0,
          "max": 30
        },
        "current": {
          "min": 0,
          "max": 1
        }
      },
      3: {
        "voltage": {
          "min": 0,
          "max": 30
        },
        "current": {
          "min": 0,
          "max": 1  
        }
      }
    },
    
    "total_power": 90, 
    "line_regulation": 0.01, 
    "load_regulation": 0.2,
    "programming_accuracy": {
      "voltage": 0.05,
      "current": 0.2  
    },
    
    "readback_accuracy": {
      "voltage": 0.05,
      "current": 0.2
    },
    
    "interfaces": ["USB", "LAN"],
    "remote_control": ["SCPI", "IVI", "Web Browser"]
  }
}

awg_profile = {
  "EDU33211A": {
    "manufacturer": "Keysight",
    "model": "EDU33211A", 
    "device_type": "Arbitrary Waveform Generator",
    
    "channels": 1,
    "max_frequency": 20e6, 
    
    "waveforms": {
      "standard": ["sine", "square", "ramp", "pulse", "triangle", "noise", "PRBS", "DC"],
      "built-in": ["cardiac", "exponential_fall", "exponential_rise", "gaussian_pulse", 
                  "haversine", "lorentz", "dlorentz", "negative_ramp", "sinc"],
      "arbitrary": {
        "memory": 8e6, 
        "max_length": 1e6,
        "sampling_rate": {
          "min": 1e-6,
          "max": 250e6
        },
        "resolution": 16
      }
    },
    
    "modulation_types": ["AM", "FM", "PM", "FSK", "BPSK", "PWM"],
    
    "amplitude": {
      "min": 1e-3,
      "max": 10
    },
    
    "dc_offset": {
      "min": -5,
      "max": 5  
    },

    "accuracy": {
      "amplitude": 0.02, 
      "frequency": 1e-6
    },
    
    "interfaces": ["USB", "LAN"], 
    "remote_control": ["SCPI", "IVI", "Web Browser"]
  }
}