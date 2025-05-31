# pytestlab/instruments/scpi_maps.py
class CommonSCPI:
    IDN = "*IDN?"
    RESET = "*RST"
    OPC_QUERY = "*OPC?"  # Operation Complete Query
    OPC_COMMAND = "*OPC"  # Operation Complete Command
    CLS = "*CLS"  # Clear Status
    ESE = "*ESE"  # Standard Event Status Enable
    ESR_QUERY = "*ESR?"  # Event Status Register Query
    SRE = "*SRE"  # Service Request Enable
    STB_QUERY = "*STB?"  # Status Byte Query
    TST_QUERY = "*TST?"  # Self-Test Query

class SystemSCPI:
    ERROR_QUERY = "SYSTem:ERRor?"
    VERSION_QUERY = "SYSTem:VERSion?"
    LOCK = "SYSTem:LOCK"
    LOCAL = "SYSTem:LOCal"
class KeysightEDU36311APSU_SCPI(CommonSCPI, SystemSCPI): # Inherits common commands
    # Based on "VOLTAGE {voltage}, (@{channel})"
    VOLTAGE_SET_BASE = "VOLTAGE"
    CURRENT_SET_BASE = "CURR"
    # Based on "OUTPut:STATe {ON|OFF}, (@{argument})"
    OUTPUT_STATE_SET_BASE = "OUTPut:STATe"
    # Based on "MEAS:VOLT? (@{channel})"
    MEAS_VOLTAGE_QUERY_BASE = "MEAS:VOLT?"
    MEAS_CURRENT_QUERY_BASE = "MEAS:CURR?"
    OUTPUT_STATE_QUERY_BASE = "OUTPut:STate?"