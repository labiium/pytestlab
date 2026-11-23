"""Native capability usage with fake transports only. No physical I/O."""

from pytestlab import AutoDevice
from pytestlab.config.bench_config import RouteEntry


class FakeIO:
    def __init__(self, responses, status_byte):
        self.responses = responses
        self.status_byte = status_byte
        self.calls = []

    def connect(self):
        pass

    def disconnect(self):
        pass

    def close(self):
        pass

    def set_timeout(self, value):
        pass

    def get_timeout(self):
        return 2000

    def set_read_termination(self, value):
        self.calls.append(("termination", value))

    def set_write_termination(self, value):
        self.calls.append(("write_termination", value))

    def write(self, command):
        self.calls.append(("write", command))

    def query(self, command, delay=None):
        self.calls.append(("query", command, delay))
        return self.responses.get(command, "0 accepted")

    def query_raw(self, command, delay=None):
        return b"\x00\n\xff"

    def read_status_byte(self):
        return self.status_byte


def main():
    wire = FakeIO({"31": "0 1000 -500 6600 0 31"}, 0x10)
    prober = AutoDevice.from_preset("suss/PA200", backend_override=wire)
    try:
        print("Position in mm:", prober.get_position())
        print("Status:", prober.get_status())
        print("Native byte:", prober.read_status_byte())
        # These commands are sent ONLY to FakeIO above; no live station is used.
        print("Fake set-home receipt:", prober.set_home(axes=("x", "y")))
        print("Fake move-home receipt:", prober.move_home(axes=("x", "y")))
        print("Fake movement receipt:", prober.move_relative(x=0.01, y=0.0))
        print("Fake protocol exchanges:", wire.calls)
    finally:
        prober.close()

    wire = FakeIO({"ID": "HP 4084B REV. 3.0"}, 0x43)
    matrix = AutoDevice.from_preset("hp/HP4084B", backend_override=wire)
    route = RouteEntry.model_validate(
        {
            "connects": [{"from": "source", "to": "dut", "path": ["P1:12"]}],
        }
    )
    try:
        matrix.apply_route("example", route)
        print("Matrix identity:", matrix.id())
        print("Matrix native byte:", matrix.read_status_byte())
        print("Fake matrix exchanges:", wire.calls)
    finally:
        matrix.close()

    for profile, command, identity in (
        ("agilent/3458A", "ID?", "HP3458A"),
        ("hp/4142B", "*IDN?", "HEWLETT PACKARD,4142B,0,4.20"),
    ):
        wire = FakeIO({command: identity}, 0)
        instrument = AutoDevice.from_preset(profile, backend_override=wire)
        try:
            print(profile, instrument.id(), instrument.read_status_byte())
        finally:
            instrument.close()


if __name__ == "__main__":
    main()
