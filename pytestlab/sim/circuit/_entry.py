from __future__ import annotations


def build_circuit_sim_backend(context):
    from pytestlab.instruments.backends.circuit_sim_backend import (
        build_circuit_sim_backend as build,
    )

    return build(context)


__all__ = ["build_circuit_sim_backend"]
