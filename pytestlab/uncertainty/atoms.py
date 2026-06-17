"""Elementary influence quantities (atoms) and the shared correlation space.

An :class:`InfluenceQuantity` is a GUM input quantity ``X_i``: an immutable
elementary source of uncertainty with a stable identity (``uid``). Two readings
that share a physical source (e.g. the same DMM gain term) reuse the same
``uid`` and are therefore automatically correlated.

The :class:`AtomRegistry` owns the atoms and the covariance matrix ``Σ_X`` over
them. By default ``Σ_X`` is diagonal (atoms independent); off-diagonal entries
are set explicitly or imported from a covariance matrix (JCGM 102).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from dataclasses import field
from enum import Enum


class Distribution(str, Enum):
    """Probability distribution assigned to an influence quantity."""

    STANDARD = "standard"  # value already expressed as a standard uncertainty
    NORMAL = "normal"
    RECTANGULAR = "rectangular"
    TRIANGULAR = "triangular"
    ARCSINE = "arcsine"  # U-shaped
    STUDENT_T = "student_t"
    CURVED_TRAPEZOID = "curved_trapezoid"


class Kind(str, Enum):
    """GUM Type A / Type B classification."""

    TYPE_A = "type_a"
    TYPE_B = "type_b"


def divisor_for(distribution: Distribution, coverage_factor: float) -> float:
    """Divisor converting a half-width / limit into a standard uncertainty."""

    if distribution in (Distribution.STANDARD, Distribution.NORMAL):
        if distribution == Distribution.NORMAL:
            if coverage_factor <= 0:
                raise ValueError("coverage_factor must be positive for normal limits.")
            return coverage_factor
        return 1.0
    if distribution == Distribution.RECTANGULAR:
        return math.sqrt(3.0)
    if distribution == Distribution.TRIANGULAR:
        return math.sqrt(6.0)
    if distribution == Distribution.ARCSINE:
        return math.sqrt(2.0)
    if distribution == Distribution.CURVED_TRAPEZOID:
        # Trapezoid with beta=1 reduces toward triangular; use sqrt(6) as a
        # conservative default. Callers needing exact beta should pre-compute u.
        return math.sqrt(6.0)
    if distribution == Distribution.STUDENT_T:
        return 1.0
    raise NotImplementedError(distribution)


@dataclass(frozen=True)
class InfluenceQuantity:
    """One elementary input quantity ``X_i`` in the GUM model."""

    uid: str
    label: str
    nominal: float
    std_uncertainty: float
    unit: str | None = None
    distribution: Distribution = Distribution.NORMAL
    degrees_of_freedom: float | None = None
    kind: Kind = Kind.TYPE_B
    source: str | None = None

    @property
    def variance(self) -> float:
        return self.std_uncertainty**2


@dataclass
class AtomRegistry:
    """Owns influence quantities and the covariance matrix over them."""

    atoms: dict[str, InfluenceQuantity] = field(default_factory=dict)
    # Off-diagonal covariances keyed by an ordered uid pair.
    _covariances: dict[tuple[str, str], float] = field(default_factory=dict)

    def mint(
        self,
        *,
        nominal: float,
        std_uncertainty: float,
        label: str,
        unit: str | None = None,
        distribution: Distribution = Distribution.NORMAL,
        degrees_of_freedom: float | None = None,
        kind: Kind = Kind.TYPE_B,
        source: str | None = None,
        key: str | None = None,
    ) -> InfluenceQuantity:
        """Create (or reuse, when ``key`` is given) an influence quantity.

        ``key`` provides identity-stable minting: repeated calls with the same
        ``key`` return the same atom, so quantities derived from the same
        physical source are correlated automatically.
        """

        uid = key if key is not None else uuid.uuid4().hex
        existing = self.atoms.get(uid)
        if existing is not None:
            return existing
        atom = InfluenceQuantity(
            uid=uid,
            label=label,
            nominal=nominal,
            std_uncertainty=std_uncertainty,
            unit=unit,
            distribution=distribution,
            degrees_of_freedom=degrees_of_freedom,
            kind=kind,
            source=source,
        )
        self.atoms[uid] = atom
        return atom

    def register(self, atom: InfluenceQuantity) -> InfluenceQuantity:
        self.atoms.setdefault(atom.uid, atom)
        return self.atoms[atom.uid]

    def get(self, uid: str) -> InfluenceQuantity:
        return self.atoms[uid]

    # -- covariance ---------------------------------------------------------
    @staticmethod
    def _pair(uid_a: str, uid_b: str) -> tuple[str, str]:
        return (uid_a, uid_b) if uid_a <= uid_b else (uid_b, uid_a)

    def covariance(self, uid_a: str, uid_b: str) -> float:
        if uid_a == uid_b:
            return self.atoms[uid_a].variance
        return self._covariances.get(self._pair(uid_a, uid_b), 0.0)

    def set_covariance(self, uid_a: str, uid_b: str, value: float) -> None:
        if uid_a == uid_b:
            raise ValueError("Use the atom's std_uncertainty to set its variance.")
        self._covariances[self._pair(uid_a, uid_b)] = value

    def set_correlation(self, uid_a: str, uid_b: str, r: float) -> None:
        if not -1.0 <= r <= 1.0:
            raise ValueError("correlation coefficient must be in [-1, 1].")
        cov = r * self.atoms[uid_a].std_uncertainty * self.atoms[uid_b].std_uncertainty
        self.set_covariance(uid_a, uid_b, cov)

    def correlation(self, uid_a: str, uid_b: str) -> float:
        u_a = self.atoms[uid_a].std_uncertainty
        u_b = self.atoms[uid_b].std_uncertainty
        if u_a == 0 or u_b == 0:
            return 0.0
        return self.covariance(uid_a, uid_b) / (u_a * u_b)


# A process-wide default registry so quantities from independent reads share one
# correlation space unless a caller deliberately isolates them.
DEFAULT_REGISTRY = AtomRegistry()


def default_registry() -> AtomRegistry:
    return DEFAULT_REGISTRY
