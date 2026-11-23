from __future__ import annotations

import pytest
from pydantic import ValidationError

from pytestlab.config.loader import load_device_profile
from pytestlab.config.vna_config import VNAConfig
from pytestlab.errors import InstrumentConfigurationError
from pytestlab.errors import InstrumentDataError
from pytestlab.instruments.VectorNetworkAnalyser import VectorNetworkAnalyser


class Transcript:
    """A real-mode device with only read-only, documented queries available."""

    is_simulated = False

    def __init__(self, overrides=None):
        self.responses = {
            "*IDN?": "Keysight Technologies,E5071C,TEST123,A.09.60",
            "*STB?": "0",
            ":STAT:OPER:COND?": "0",
            ":INIT1:CONT?": "0",
            ":FORM:DATA?": "ASC",
            ":SENS1:SWE:TYPE?": "LIN",
            ":SENS1:FREQ:SPAN?": "+3.50E2",
            ":SENS1:OFFS:STAT?": "0",
            ":CALC1:FSIM:STAT?": "0",
            ":SENS1:SWE:POIN?": "3",
            ":CALC1:PAR:COUN?": "2",
            ":CALC1:PAR1:DEF?": "S21",
            ":CALC1:PAR2:DEF?": "S11",
            ":CALC1:TRAC1:EQU:STAT?": "0",
            ":CALC1:TRAC2:EQU:STAT?": "0",
            ":CALC1:TRAC1:TRAN:TIME:STAT?": "0",
            ":CALC1:TRAC2:TRAN:TIME:STAT?": "0",
            ":CALC1:TRAC1:DATA:XAX?": "100,275,450",
            ":CALC1:TRAC2:DATA:XAX?": "100,275,450",
            ":CALC1:TRAC1:DATA:SDAT?": "+0.1,0.2,0.3,0.4,0.5,-0.6",
            ":CALC1:TRAC2:DATA:SDAT?": "1,0,0.5,-0.5,1,-1",
        }
        self.responses.update(overrides or {})
        self.queries = []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def close(self):
        pass

    def query(self, command, delay=None):
        self.queries.append(command)
        value = self.responses[command]
        return value.pop(0) if isinstance(value, list) else value

    def write(self, command):
        raise AssertionError(f"readback sent write: {command}")


def _analyser(overrides=None):
    config = load_device_profile("keysight/E5071C_VNA")
    assert isinstance(config, VNAConfig)
    backend = Transcript(overrides)
    return VectorNetworkAnalyser(config, backend), backend


@pytest.mark.parametrize(
    "mode, axis, frequencies",
    [
        ("LIN", "100,275,450", [100, 275, 450]),
        ("LOG", "100,205.735,450", [100, 205.735, 450]),
    ],
)
def test_e5071c_returns_observed_axis_and_reordered_traces(mode, axis, frequencies):
    analyser, backend = _analyser(
        {
            ":SENS1:SWE:TYPE?": mode,
            ":CALC1:TRAC1:DATA:XAX?": axis,
            ":CALC1:TRAC2:DATA:XAX?": axis,
        }
    )
    assert analyser.supports_operation("sparameter_data")
    assert "sparameter_data" in analyser.list_operations(include_unsupported=False)
    assert not backend.queries

    result = analyser.get_s_parameter_data()
    assert result.frequencies == frequencies
    assert result.param_names == ["S11", "S21"]  # Request order, not front-panel slot order.
    assert result.s_params == [[1 + 0j, 0.5 - 0.5j, 1 - 1j], [0.1 + 0.2j, 0.3 + 0.4j, 0.5 - 0.6j]]
    assert result.axis_source == "instrument"
    assert result.trace_identity_verified
    assert [q for q in backend.queries if "SDAT" in q] == [
        ":CALC1:TRAC2:DATA:SDAT?",
        ":CALC1:TRAC1:DATA:SDAT?",
    ]
    assert "SYST:ERR?" not in backend.queries


@pytest.mark.parametrize(
    "override, reason",
    [
        ({"*IDN?": "Keysight,E5072A,TEST123,A.10.00"}, "did not identify"),
        ({"*IDN?": "Keysight,E5071C,TEST123,A.09.59"}, "requires firmware"),
        ({"*STB?": "4"}, "error queue"),
        ({":STAT:OPER:COND?": "16"}, "no measurement"),
        ({":STAT:OPER:COND?": "32"}, "pending trigger"),
        ({":INIT1:CONT?": "1"}, "on Hold"),
        ({":FORM:DATA?": "REAL32"}, "requires ASCII"),
        ({":SENS1:SWE:TYPE?": "POW"}, "LIN and LOG"),
        ({":SENS1:FREQ:SPAN?": "0"}, "nonzero frequency span"),
        ({":SENS1:OFFS:STAT?": "1"}, "frequency offset off"),
        ({":CALC1:FSIM:STAT?": "1"}, "fixture simulator off"),
        ({":CALC1:TRAC1:TRAN:TIME:STAT?": "1"}, "time-domain transforms off"),
        ({":CALC1:TRAC1:EQU:STAT?": "1"}, "equation"),
    ],
)
def test_e5071c_rejects_unsafe_sweep_state_before_data(override, reason):
    analyser, backend = _analyser(override)
    with pytest.raises(InstrumentConfigurationError, match=reason):
        analyser.get_s_parameter_data()
    assert not any(":DATA:" in command for command in backend.queries)


@pytest.mark.parametrize(
    "override, reason",
    [
        ({":CALC1:PAR1:DEF?": "S11"}, "found 2"),
        ({":CALC1:PAR1:DEF?": "A"}, "found 0"),
        ({":CALC1:TRAC1:DATA:XAX?": "100,276,450"}, "same frequency axis"),
        ({":CALC1:TRAC2:DATA:XAX?": "100,100,450"}, "not strictly increasing"),
        ({":CALC1:TRAC2:DATA:XAX?": "100,275"}, "Expected 3"),
        ({":CALC1:TRAC2:DATA:SDAT?": "1,0,0.5,-0.5"}, "Expected 6"),
        ({":CALC1:TRAC2:DATA:SDAT?": "1,0,,0,1,0"}, "empty field"),
        ({":CALC1:TRAC2:DATA:SDAT?": "1,0,1.#QNB,0,1,0"}, "not a finite ASCII"),
        ({":CALC1:TRAC2:DATA:SDAT?": "1,0,1e400,0,1,0"}, "non-finite"),
        ({":SENS1:SWE:POIN?": ["3", "4"]}, "settings changed"),
        ({":CALC1:PAR2:DEF?": ["S11", "S11", "S22"]}, "no longer identifies"),
        ({":CALC1:TRAC2:DATA:XAX?": ["100,275,450", "110,275,450"]}, "axis changed"),
    ],
)
def test_e5071c_rejects_ambiguous_or_malformed_data(override, reason):
    analyser, _ = _analyser(override)
    with pytest.raises(InstrumentDataError, match=reason):
        analyser.get_s_parameter_data()


def test_indexed_readback_profile_requires_complete_query_bindings():
    analyser, _ = _analyser()
    config = analyser.config
    scpi = config.scpi
    assert scpi and scpi.queries
    del scpi.queries["readback_trace_axis"]
    with pytest.raises(ValidationError, match="VNA readback requires query aliases: trace_axis"):
        VNAConfig.model_validate(config.model_dump_internal(mode="python"))
