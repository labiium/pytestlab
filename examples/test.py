from pytestlab.instruments import AutoInstrument
import asyncio

async def main():
    osc = await AutoInstrument.from_config("keysight/DSOX1204G")
    print(await osc.id())

asyncio.run(main())
