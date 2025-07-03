import asyncio
from pytestlab.instruments import AutoInstrument
from pytestlab.instruments import PowerSupply

async def main():
    """A simple script to test the simulation functionality."""
    psu: PowerSupply = await AutoInstrument.from_config(
        "pytestlab/profiles/keysight/EDU36311A_recorded.yaml", 
        simulate=True
    )
    await psu.connect_backend()
    await psu.set_voltage(3.3)
    await psu.set_current(0.5)
    await psu.output(1, True)
    await asyncio.sleep(1)
    idn = await psu._query("*IDN?")
    print(f"Received IDN: {idn}")
    await psu.output(1, False)
    await psu.close()

if __name__ == "__main__":
    asyncio.run(main())