"""Sweep a simulated PSU and read a simulated DMM without opening hardware."""

from pytestlab import AutoInstrument


def main():
    psu = AutoInstrument.from_preset("keysight/EDU36311A", simulate=True)
    dmm = AutoInstrument.from_preset("keysight/34470A", simulate=True)
    try:
        # These simulators are independent: DMM readings do not track the PSU.
        try:
            for voltage in (0.1, 0.2, 0.3):
                psu.channel(1).set(voltage=voltage).on()
                setpoint = float(psu.channel(1).get_voltage())
                reading = dmm.measure("dc_voltage").values
                print(f"PSU setpoint {setpoint:.1f} V; independent DMM reading {reading}")
        finally:
            psu.channel(1).off()
    finally:
        dmm.close()
        psu.close()


if __name__ == "__main__":
    main()
