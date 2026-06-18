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
from . import umath
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
from .conformity import assess_conformity
from .corrections import Correction
from .corrections import apply_correction
from .digital_export import DCC_SCHEMA_VERSION
from .digital_export import DSI_SCHEMA_VERSION
from .digital_export import quantity_to_dsi
from .digital_export import quantity_to_unsigned_dcc_xml
from .digital_export import validate_dcc_profile_xml
from .digital_export import verify_cached_schema_files
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
from .metrology import CalibrationCertificate
from .metrology import CalibrationCertificateEntry
from .metrology import ConformityResult
from .metrology import MeasurementModel
from .metrology import ResultProvenance
from .metrology import ToleranceInterval
from .metrology import TraceabilityRef
from .metrology import is_report_grade
from .metrology import report_grade_blockers
from .metrology import resolve_traceability_ref
from .montecarlo import MonteCarloResult
from .montecarlo import adaptive_monte_carlo
from .montecarlo import monte_carlo
from .montecarlo import shortest_coverage_interval
from .multivariate import ComplexQuantity
from .multivariate import QuantityVector
from .multivariate import covariance_between
from .quantity import CorrelationComponentWarning
from .quantity import Quantity
from .quantity_array import ComplexQuantityArray
from .quantity_array import QuantityArray
from .quick import correlated_values
from .quick import correlated_values_norm
from .quick import correlation_matrix
from .quick import covariance_matrix
from .quick import from_ufloat
from .quick import from_ufloats
from .quick import nominal_value
from .quick import nominal_values
from .quick import std_dev
from .quick import std_devs
from .quick import to_ufloat_correlated
from .quick import uq
from .units import UnitCompatibilityError
from .units import require_dsi_unit
from .units import to_dsi_unit
from .validation import ValidationReport
from .validation import validate
from .validation import validate_model

__all__ = [
    "Quantity",
    "CorrelationComponentWarning",
    "QuantityArray",
    "ComplexQuantityArray",
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
    "assess_conformity",
    "quantity_to_dsi",
    "quantity_to_unsigned_dcc_xml",
    "validate_dcc_profile_xml",
    "verify_cached_schema_files",
    "DCC_SCHEMA_VERSION",
    "DSI_SCHEMA_VERSION",
    "to_dsi_unit",
    "require_dsi_unit",
    "TraceabilityRef",
    "CalibrationCertificate",
    "CalibrationCertificateEntry",
    "MeasurementModel",
    "ResultProvenance",
    "ConformityResult",
    "ToleranceInterval",
    "is_report_grade",
    "report_grade_blockers",
    "resolve_traceability_ref",
    "functions",
    "umath",
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
    "uq",
    "nominal_value",
    "std_dev",
    "nominal_values",
    "std_devs",
    "correlated_values",
    "correlated_values_norm",
    "covariance_matrix",
    "correlation_matrix",
    "from_ufloat",
    "from_ufloats",
    "to_ufloat_correlated",
]
