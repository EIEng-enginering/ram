"""Qualified analytical checks for independent repairable blocks."""
from math import expm1, isfinite, prod

import numpy as np


def component(mtbf: float, mttr: float) -> float:
    if not (isfinite(mtbf) and isfinite(mttr) and mtbf > 0 and mttr >= 0):
        raise ValueError("Require positive MTBF and nonnegative MTTR.")
    return 1 / (1 + mttr / mtbf)


def independent_group(kind: str, availabilities: list[float], k: int = 1) -> float:
    if not availabilities or any(not 0 <= a <= 1 for a in availabilities):
        raise ValueError("Supply one or more probabilities in [0, 1].")
    if kind == "series":
        return prod(availabilities)
    if kind == "parallel":
        return 1 - prod(1 - a for a in availabilities)
    if kind != "kofn" or not 1 <= k <= len(availabilities):
        raise ValueError("Unknown group or invalid voting threshold.")
    probabilities = [1.0]
    for a in availabilities:
        updated = [0.0] * (len(probabilities) + 1)
        for n, probability in enumerate(probabilities):
            updated[n] += probability * (1 - a)
            updated[n + 1] += probability * a
        probabilities = updated
    return sum(probabilities[k:])


def hidden_periodic(rate: float, interval: float) -> tuple[float, float]:
    """Perfect periodic discovery and instantaneous restoration."""
    if not (isfinite(rate) and isfinite(interval) and rate >= 0 and interval > 0):
        raise ValueError("Invalid hidden-failure basis.")
    x = rate * interval
    if not isfinite(x):
        raise ValueError("Rate times interval is too large.")
    exact = x * (0.5 - x / 6 + x * x / 24) if x < 1e-4 else 1 + expm1(-x) / x
    return x / 2, exact


def cold_standby(rate: float, repair_rate: float) -> float:
    """Identical units, perfect switch, single exponential repair channel."""
    if not (isfinite(rate) and isfinite(repair_rate) and rate >= 0 and repair_rate > 0):
        raise ValueError("Invalid Markov rates.")
    ratio = rate / repair_rate
    if ratio > 1:
        inverse = repair_rate / rate
        return (inverse + inverse**2) / (1 + inverse + inverse**2)
    return (1 + ratio) / (1 + ratio + ratio**2)


def stationary(generator: list[list[float]], up: list[int]) -> float:
    """Finite CTMC with a unique stationary distribution."""
    q = np.asarray(generator, dtype=float)
    if q.ndim != 2 or q.shape[0] != q.shape[1] or not len(q) or not np.isfinite(q).all():
        raise ValueError("Invalid generator dimensions or values.")
    if any(type(i) is not int or i < 0 or i >= len(q) for i in up) or len(set(up)) != len(up):
        raise ValueError("Invalid up-state list.")
    off = q.copy()
    np.fill_diagonal(off, 0)
    if (off < 0).any() or (np.diag(q) > 0).any() or not np.allclose(q.sum(axis=1), 0):
        raise ValueError("Invalid generator transition rates.")
    equations = q.T.copy()
    equations[-1] = 1
    rhs = np.zeros(len(q))
    rhs[-1] = 1
    try:
        p = np.linalg.solve(equations, rhs)
    except np.linalg.LinAlgError as error:
        raise ValueError("Generator has no unique stationary distribution.") from error
    return float(p[up].sum())


def standby_generator(active_rate, standby_rate, repair_rate, switch_failure=0.0):
    """Symmetric active units, one repair channel, immediate switch, no preemption.

    A failed switch keeps service down until the active unit is restored. Use
    standby_rate=0 for cold, a lower rate for warm, or active_rate for hot.
    """
    a, d, r, s = active_rate, standby_rate, repair_rate, switch_failure
    if any(not isfinite(x) for x in (a, d, r, s)) or not (a >= 0 and d >= 0 and r > 0 and 0 <= s <= 1):
        raise ValueError("Invalid standby parameters.")
    return [[-(a + d), a * (1 - s) + d, 0, a * s],
            [r, -(r + a), a, 0], [0, r, -r, 0], [r, 0, 0, -r]]


def standby_pair(active_rate, standby_rate, repair_rate, switch_failure=0.0):
    return stationary(standby_generator(active_rate, standby_rate, repair_rate, switch_failure), [0, 1])


def rbd(tree, availability):
    """Evaluate a nested independent success diagram and reject repeated assets."""
    used = set()

    def visit(node):
        if isinstance(node, str):
            if node in used:
                raise ValueError(f"Repeated asset {node} breaks the independent-block basis.")
            used.add(node)
            return availability[node]
        return independent_group(node["kind"], [visit(child) for child in node["children"]], node.get("k", 1))

    result = visit(tree)
    if not 0 <= result <= 1:
        raise ValueError("Block availability outside [0, 1].")
    return result


def constant_rate_estimate(failures, exposure_h, confidence=.95):
    """Homogeneous Poisson event count over approved total exposure."""
    from scipy.stats import chi2
    if type(failures) is not int or failures < 0 or not isfinite(exposure_h) or not exposure_h > 0:
        raise ValueError("Require a nonnegative count and positive exposure hours.")
    if not 0 < confidence < 1:
        raise ValueError("Invalid confidence.")
    alpha = 1 - confidence
    return {"events": failures, "exposure_h": exposure_h, "rate_per_h": failures / exposure_h,
            "confidence": confidence,
            "interval_per_h": [float(chi2.ppf(alpha / 2, 2 * failures) / (2 * exposure_h)) if failures else 0,
                               float(chi2.ppf(1 - alpha / 2, 2 * (failures + 1)) / (2 * exposure_h))]}
