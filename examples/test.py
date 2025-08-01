from pytestlab.instruments import AutoInstrument

def main():
    osc = AutoInstrument.from_config("keysight/DSOX1204G")
    print(osc.id())

main()
