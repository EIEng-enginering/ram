"""Dimensional units catalogue and validated conversion to canonical units.

Canonical units: hours (h) for durations, per calendar or operating hour for
rates (the exposure basis is carried separately and is never converted
implicitly), fraction for proportions, m3 for actual volume, Sm3 for standard
volume, t for mass, MWh for energy and MW for power. Year means 8,760 h
(365 d) unless the explicit ``yr_8766`` unit is used. Month is rejected as a
duration because its length is ambiguous; enter days or hours.
"""
from dataclasses import dataclass
from math import isfinite
import re

# dimension -> canonical unit
CANONICAL = {
    "time": "h", "rate": "1/h", "fraction": "fraction", "dimensionless": "1",
    "volume": "m3", "std_volume": "Sm3", "volume_rate": "m3/h", "std_volume_rate": "Sm3/h",
    "mass": "t", "mass_rate": "t/h", "energy": "MWh", "power": "MW", "count": "count",
}

_BBL = 0.158987294928  # m3 per US oil barrel (exact by definition of 42 US gal)

# alias -> (dimension, factor to canonical)
_UNITS = {
    # time
    "h": ("time", 1.0), "hr": ("time", 1.0), "hrs": ("time", 1.0), "hour": ("time", 1.0), "hours": ("time", 1.0),
    "min": ("time", 1 / 60), "minute": ("time", 1 / 60), "minutes": ("time", 1 / 60),
    "s": ("time", 1 / 3600), "sec": ("time", 1 / 3600),
    "d": ("time", 24.0), "day": ("time", 24.0), "days": ("time", 24.0),
    "wk": ("time", 168.0), "week": ("time", 168.0), "weeks": ("time", 168.0),
    "yr": ("time", 8760.0), "a": ("time", 8760.0), "year": ("time", 8760.0), "years": ("time", 8760.0),
    "yr_8766": ("time", 8766.0),
    # rates (per unit exposure time)
    "1/h": ("rate", 1.0), "/h": ("rate", 1.0), "per h": ("rate", 1.0), "per hour": ("rate", 1.0),
    "1/d": ("rate", 1 / 24), "/d": ("rate", 1 / 24), "per day": ("rate", 1 / 24),
    "1/yr": ("rate", 1 / 8760), "/yr": ("rate", 1 / 8760), "per year": ("rate", 1 / 8760),
    "1/a": ("rate", 1 / 8760), "/a": ("rate", 1 / 8760),
    "per 1e6 h": ("rate", 1e-6), "/1e6 h": ("rate", 1e-6), "per million hours": ("rate", 1e-6),
    "fpmh": ("rate", 1e-6), "1e-6/h": ("rate", 1e-6), "fit": ("rate", 1e-9),
    # fractions
    "fraction": ("fraction", 1.0), "-": ("fraction", 1.0), "%": ("fraction", 0.01), "percent": ("fraction", 0.01),
    # dimensionless parameters (shape, sigma)
    "1": ("dimensionless", 1.0), "dimensionless": ("dimensionless", 1.0),
    # actual volume
    "m3": ("volume", 1.0), "m³": ("volume", 1.0), "l": ("volume", 1e-3), "kl": ("volume", 1.0),
    "bbl": ("volume", _BBL), "ml": ("volume", 1e-6),
    "sm3": ("std_volume", 1.0), "msm3": ("std_volume", 1e6), "ksm3": ("std_volume", 1e3),
    # volume rates
    "m3/h": ("volume_rate", 1.0), "m³/h": ("volume_rate", 1.0), "m3/d": ("volume_rate", 1 / 24),
    "m³/d": ("volume_rate", 1 / 24), "l/s": ("volume_rate", 3.6), "bbl/d": ("volume_rate", _BBL / 24),
    "bpd": ("volume_rate", _BBL / 24), "kbbl/d": ("volume_rate", 1000 * _BBL / 24),
    "sm3/h": ("std_volume_rate", 1.0), "sm3/d": ("std_volume_rate", 1 / 24),
    "msm3/d": ("std_volume_rate", 1e6 / 24),
    # mass
    "t": ("mass", 1.0), "kg": ("mass", 1e-3), "t/h": ("mass_rate", 1.0), "kg/s": ("mass_rate", 3.6),
    "t/d": ("mass_rate", 1 / 24), "kg/h": ("mass_rate", 1e-3),
    # energy and power
    "mwh": ("energy", 1.0), "kwh": ("energy", 1e-3), "gj": ("energy", 1 / 3.6), "gwh": ("energy", 1e3),
    "mw": ("power", 1.0), "kw": ("power", 1e-3),
    "count": ("count", 1.0),
}

AMBIGUOUS = {"month": "Month length is ambiguous; enter days or hours.",
             "mo": "Month length is ambiguous; enter days or hours.",
             "m": "'m' is ambiguous (minute, metre or month); use min, m3 or days."}

# library field -> required dimension
FIELD_DIMENSIONS = {
    "failure_rate_hour": "rate", "mtbf_hours": "time", "weibull_shape": "dimensionless",
    "weibull_scale_hours": "time", "lognormal_median_hours": "time", "lognormal_sigma": "dimensionless",
    "logistics_hours": "time", "mobilisation_hours": "time", "active_repair_hours": "time",
    "proof_test_hours": "time", "capacity_loss_fraction": "fraction",
}


class UnitError(ValueError):
    """Unknown, ambiguous or dimensionally incompatible unit."""


@dataclass(frozen=True)
class Quantity:
    value: float          # canonical value
    unit: str             # canonical unit
    dimension: str
    original_value: str   # text exactly as supplied
    original_unit: str    # unit text exactly as supplied


def normalise(unit):
    if not isinstance(unit, str) or not unit.strip():
        raise UnitError("A unit must be supplied.")
    key = re.sub(r"\s+", " ", unit.strip()).lower()
    if key in AMBIGUOUS:
        raise UnitError(AMBIGUOUS[key])
    if key not in _UNITS:
        raise UnitError(f"Unknown unit '{unit}'.")
    return key


def dimension(unit):
    return _UNITS[normalise(unit)][0]


def convert(value, unit, to_unit):
    """Convert a finite number between units of the same dimension only."""
    a, b = _UNITS[normalise(unit)], _UNITS[normalise(to_unit)]
    if a[0] != b[0]:
        raise UnitError(f"Cannot convert {a[0]} ({unit}) to {b[0]} ({to_unit}).")
    if type(value) not in (int, float) or not isfinite(value):
        raise UnitError("Value must be a finite number.")
    return value * a[1] / b[1]


def to_canonical(value, unit, expected=None):
    """Parse a raw cell and return a Quantity. Blank is not zero: blank raises."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise UnitError("Blank value: a missing value is not zero and must stay missing.")
    original = str(value).strip() if isinstance(value, str) else repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, bool):
        raise UnitError("Boolean is not a numeric value.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise UnitError(f"'{value}' is not numeric.") from error
    if not isfinite(number):
        raise UnitError("Value must be finite.")
    dim, factor = _UNITS[normalise(unit)]
    if expected is not None and dim != expected:
        raise UnitError(f"Unit '{unit}' is {dim}; this field requires {expected} ({CANONICAL[expected]}).")
    return Quantity(number * factor, CANONICAL[dim], dim, original, str(unit).strip())


def convert_exposure(rate_per_h, from_basis, to_basis, utilisation=None):
    """Operating and calendar exposure are separate bases.

    A conversion requires an explicit, documented utilisation (operating hours
    per calendar hour) in (0, 1]. No default is assumed.
    """
    bases = {"operating", "calendar"}
    if from_basis not in bases or to_basis not in bases:
        raise UnitError("Exposure basis must be operating or calendar.")
    if from_basis == to_basis:
        return rate_per_h
    if utilisation is None or type(utilisation) not in (int, float) or not 0 < utilisation <= 1:
        raise UnitError("Converting exposure bases requires an explicit utilisation in (0, 1].")
    return rate_per_h * utilisation if from_basis == "operating" else rate_per_h / utilisation
