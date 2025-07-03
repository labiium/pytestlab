import asyncio

async def main(instrument):
    """
    This script will be executed by the CLI's `sim-profile record` command.
    The 'instrument' object is passed to this function.
    """
    print("--- Starting test script ---")

    # The 'instrument' object is already connected and wrapped with the recording backend.
    
    # Perform some basic operations
    idn = await instrument.id()
    print(f"IDN: {idn}")

    await instrument.set_voltage(1, 1.5)
    print("Voltage set to 1.5V on channel 1")

    await instrument.set_current(1, 0.1)
    print("Current set to 0.1A on channel 1")

    await instrument.output(1, True)
    print("Output enabled on channel 1")

    await instrument.output(1, False)
    print("Output disabled on channel 1")

    print("--- Test script finished ---")