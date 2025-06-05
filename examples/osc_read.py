import asyncio
from pytestlab.instruments import AutoInstrument

# loading the instruments
async def main():

    osc = AutoInstrument.from_config("keysight/DSOX1204G")

    data = await osc.read_channels(1)

    # turn on display of channel 1
    await osc.display_channel(1, state=True)
    
    print(data)


asyncio.run(main())