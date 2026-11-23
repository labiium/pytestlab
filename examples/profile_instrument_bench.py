"""Offline discovery example for the declarative legacy-controller profiles."""

from pytestlab import AutoInstrument

for profile in (
    "hp/HP4084B_legacy",
    "suss/PA200_legacy",
    "agilent/3458A_legacy",
    "hp/4142B_legacy",
):
    instrument = AutoInstrument.from_preset(profile, simulate=True)
    print(profile)
    for operation in instrument.list_operations(include_unsupported=False):
        print(instrument.describe_operation(operation))
