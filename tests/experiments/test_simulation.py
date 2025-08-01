import time
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments import PowerSupply

def main():
    """A simple script to test the simulation functionality."""
    psu: PowerSupply = AutoInstrument.from_config(
        "pytestlab/profiles/keysight/EDU36311A_recorded.yaml",
        simulate=True
    )
    psu.connect_backend()
    psu.set_voltage(3.3)
    psu.set_current(0.5)
    psu.output(1, True)
    time.sleep(1)
    idn = psu._query("*IDN?")
    print(f"Received IDN: {idn}")
    psu.output(1, False)
    psu.close()

if __name__ == "__main__":
    main()
