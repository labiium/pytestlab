from __future__ import annotations

from pytestlab.twin import CharacterizedScopeTwin
from pytestlab.twin import TwinDomain
from pytestlab.twin import TwinIdentity
from pytestlab.twin import TwinRegistry
from pytestlab.twin import residual_metric
from pytestlab.twin.residuals import ResidualReport


def test_twin_registry_keys_characterized_scope_by_identity() -> None:
    identity = TwinIdentity(model="MXR404A", serial_hash="sha256:redacted")
    domain = TwinDomain(quantities=("rms",), amplitude_v=(0.1, 1.0))
    report = ResidualReport.build(
        twin_identity=identity,
        domain=domain,
        metrics=[
            residual_metric(
                "rms",
                hardware_nominal=1.0,
                twin_nominal=1.001,
                hardware_u=0.01,
                twin_u=0.01,
            )
        ],
        context={"amplitude_v": 0.5},
    )
    twin = CharacterizedScopeTwin(identity=identity, domain=domain, residual_report=report)

    registry = TwinRegistry([twin])

    assert registry.get(identity) is twin
    assert registry.by_model("MXR404A") == [twin]
