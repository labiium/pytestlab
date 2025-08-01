import time

def main(instrument):
    """A simple script to test the recording functionality."""
    instrument.set_voltage(3.3)
    instrument.set_current(0.5)
    instrument.output(1, True)
    time.sleep(1)
    instrument._query("*IDN?")
    instrument.output(1, False)
