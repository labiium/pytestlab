import asyncio

async def main(instrument):
    """A simple script to test the recording functionality."""
    await instrument.set_voltage(3.3)
    await instrument.set_current(0.5)
    await instrument.output(1, True)
    await asyncio.sleep(1)
    await instrument._query("*IDN?")
    await instrument.output(1, False)