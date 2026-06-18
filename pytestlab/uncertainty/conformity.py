"""Uncertainty-aware conformity assessment helpers.

This is a structured JCGM-106/ILAC-G8-oriented result surface. It deliberately
returns a record, not a bare boolean. Specific PFA/PFR remains null unless the
caller supplies a prior model; PyTestLab does not infer one.
"""

from __future__ import annotations

from .metrology import ConformityResult
from .metrology import ToleranceInterval
from .quantity import Quantity


def assess_conformity(
    measured: Quantity,
    tolerance: ToleranceInterval,
    *,
    coverage_factor: float = 2.0,
    guard_band_factor: float = 1.0,
    decision_rule_name: str = "guard_band_w_equals_k_u",
    decision_rule_source: str = "JCGM 106 / ILAC G8 policy required from caller",
    decision_rule_agreed_at: str | None = None,
    measurand_prior_ref: str | None = None,
    specific_risk: dict[str, float | None] | None = None,
) -> ConformityResult:
    """Return a structured conformity decision for a scalar quantity.

    The acceptance interval is the tolerance interval shrunk by
    ``guard_band_factor * expanded_uncertainty`` on each bounded side.
    """

    u_exp = measured.u * coverage_factor
    guard_band = guard_band_factor * u_exp
    lower = tolerance.lower
    upper = tolerance.upper
    acceptance_lower = None if lower is None else lower + guard_band
    acceptance_upper = None if upper is None else upper - guard_band
    y = measured.nominal

    if (
        acceptance_lower is not None
        and acceptance_upper is not None
        and acceptance_lower > acceptance_upper
    ):
        decision = "indeterminate"
    elif acceptance_lower is not None and y < acceptance_lower:
        decision = "fail" if lower is not None and y < lower else "conditional_fail"
    elif acceptance_upper is not None and y > acceptance_upper:
        decision = "fail" if upper is not None and y > upper else "conditional_fail"
    else:
        decision = "pass"

    if measurand_prior_ref is None:
        risk = {"pfa": None, "pfr": None}
    else:
        risk = specific_risk or {"pfa": None, "pfr": None}

    return ConformityResult(
        tolerance=tolerance,
        decision_rule={
            "name": decision_rule_name,
            "guard_band_w": guard_band,
            "basis": f"w={guard_band_factor}*U, U={coverage_factor}*u",
            "source": decision_rule_source,
            "agreed_at": decision_rule_agreed_at,
        },
        measured={"y": y, "u": measured.u, "U": u_exp, "k": coverage_factor},
        decision=decision,
        measurand_prior_ref=measurand_prior_ref,
        specific_risk=risk,
        statement=f"{decision}: y={y:g}, U={u_exp:g}, k={coverage_factor:g}",
    )
