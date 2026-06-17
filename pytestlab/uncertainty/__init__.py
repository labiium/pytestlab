"""GUM / JCGM 101 / 102 compliant uncertainty engine.

Public API:

- :class:`Quantity` — scalar measurand carrying a gradient over the atom space.
- :class:`AtomRegistry`, :class:`InfluenceQuantity`, :class:`Distribution`,
  :class:`Kind` — the elementary input-quantity layer and shared correlation space.
- :class:`UncertaintyBudget` / :class:`UncertaintyReport` — GUM §7 reporting.
- math functions (:func:`sqrt`, :func:`log`, :func:`exp`, ...) for arbitrary-
  function propagation.
"""

from __future__ import annotations

from . import functions
from .atoms import AtomRegistry
from .atoms import Distribution
from .atoms import InfluenceQuantity
from .atoms import Kind
from .atoms import default_registry
from .atoms import divisor_for
from .budget import BudgetEntry
from .budget import UncertaintyBudget
from .budget import UncertaintyReport
from .budget import round_to_significant
from .corrections import Correction
from .corrections import apply_correction
from .functions import absolute
from .functions import atan2
from .functions import cos
from .functions import exp
from .functions import log
from .functions import log10
from .functions import power
from .functions import sin
from .functions import sqrt
from .functions import tan
from .montecarlo import MonteCarloResult
from .montecarlo import adaptive_monte_carlo
from .montecarlo import monte_carlo
from .montecarlo import shortest_coverage_interval
from .multivariate import ComplexQuantity
from .multivariate import QuantityVector
from .multivariate import covariance_between
from .quantity import Quantity
from .units import UnitCompatibilityError
from .validation import ValidationReport
from .validation import validate
from .validation import validate_model

__all__ = [
    "Quantity",
    "AtomRegistry",
    "InfluenceQuantity",
    "Distribution",
    "Kind",
    "default_registry",
    "divisor_for",
    "UncertaintyBudget",
    "UncertaintyReport",
    "BudgetEntry",
    "round_to_significant",
    "UnitCompatibilityError",
    "functions",
    "sqrt",
    "log",
    "log10",
    "exp",
    "sin",
    "cos",
    "tan",
    "atan2",
    "power",
    "absolute",
    "monte_carlo",
    "adaptive_monte_carlo",
    "shortest_coverage_interval",
    "MonteCarloResult",
    "validate",
    "validate_model",
    "ValidationReport",
    "Correction",
    "apply_correction",
    "QuantityVector",
    "ComplexQuantity",
    "covariance_between",
]
