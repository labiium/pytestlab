
oscilloscpe_description = {
    "MXR054A": {
    "manufacturer": "Keysight",
    "model": "MXR054A", 
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "bandwidth": "500 MHz",
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
    },
    "MXR058A": {
    "manufacturer": "Keysight",
    "model": "MXR058A", 
    "device_type": "oscilloscope",
    "channels": {
      1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
      2: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },  
      3: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
      4: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
      5: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
      6: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }, 
      7: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
      8: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "bandwidth": "500 MHz",  
    "analog_channels": 8,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

    "MXR104A": {
    # Same as MXR054A except:
    "model": "MXR104A",
    "bandwidth": "1 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR108A": {
    # Same as MXR058A except: 
    "model": "MXR108A",
    "bandwidth": "1 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR204A": {
    # Same as MXR054A except:
    "model": "MXR204A",
    "bandwidth": "2 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR208A": {
    # Same as MXR058A except:
    "model": "MXR208A",
    "bandwidth": "2 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR254A": {
    # Same as MXR054A except:
    "model": "MXR254A",
    "bandwidth": "2.5 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },
  
  "MXR258A": {
    # Same as MXR058A except:
    "model": "MXR258A",
    "bandwidth": "2.5 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR404A": {
    # Same as MXR054A except:
    "model": "MXR404A", 
    "bandwidth": "4 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR408A": {
    # Same as MXR058A except:
    "model": "MXR408A",
    "bandwidth": "4 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR604A": {
    # Same as MXR054A except:
    "model": "MXR604A",
    "bandwidth": "6 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  },

  "MXR608A": {
    # Same as MXR058A except:
    "model": "MXR608A",
    "bandwidth": "6 GHz",
    "device_type": "oscilloscope",
    "channels": {
        1: {
        "description": "Input Channel 1",
        "min": -5.0,               
        "max": 5.0,
        "input_coupling": ["AC", "DC"],   
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        2: {
        "description": "Input Channel 2",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,  
        "probe_attenuation": [1, 10, 100]
        },
        3: {
        "description": "Input Channel 3",
        "min": -5.0,
        "max": 5.0,
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        },
        4: {
        "description": "Input Channel 4",
        "min": -5.0,
        "max": 5.0, 
        "input_coupling": ["AC", "DC"],
        "input_impedance": 1e6,
        "probe_attenuation": [1, 10, 100]
        }
    },
    "timebase": {
        "min_scale": 5e-12,
        "max_scale": 200,
        "time_units": ["s", "ms", "us", "ns"]
    },
    "trigger": {
        "available_modes": ["EDGE", "PULSE", "TIMEOUT", "WINDOW"],
        "slope": ["RISING", "FALLING", "EITHER"],
        "external_trigger_input": ["AUX"] 
    },
    "analog_channels": 4,
    "sampling_rate": "16 GSa/s",
    "standard_memory": "200 Mpts/ch",
    "waveform_update_rate": "> 200,000 wfms/sec",
    "jitter_analysis": {
        "available_types": ["RMS"],
        "jitter_sources": ["Time Interval Error"],
        "analysis_depth": 1e6,
        "histogram_bins": 256, 
        "modulation_analysis": False,
        "real_time_analysis": False,
        "min_jitter_measurement": 1e-12,
        "max_jitter_measurement": 1e-3
    }
  }
}