"""Print expected (independent) vs simulated values for the WP2/WP3 reference cases.

Run: python tools/verify_references.py  > TEST_RESULTS/REFERENCE_VERIFICATION.txt
Also runs negative controls: the CTMC reference with the switch-failure term
removed must be rejected at the same tolerance, showing the check has power.
"""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import numpy as np  # noqa: E402

from test_wp3_methods import Availability, ctmc, mc  # noqa: E402
from test_wp2_physical import network, unit, edge  # noqa: E402

rows = []


def check(name, model, expected, n=400, bias=0.0015, alt=None):
    t = time.perf_counter()
    mean, se = mc(model, n)
    ok = abs(mean - expected) < 4 * se + bias
    line = f"{name:<48} expected {expected:.6f}  simulated {mean:.6f} ± {1.96 * se:.6f} (95%)  n={n}  {'PASS' if ok else 'FAIL'}"
    if alt is not None:
        rejected = abs(mean - alt) >= 4 * se + bias
        line += f" | negative control {alt:.6f} {'rejected' if rejected else 'NOT rejected'}"
    rows.append(line + f"  [{time.perf_counter() - t:.1f}s]")


a = Availability()
lam, mu = 1 / 100, 1 / 20
for s, f, crews in ((0.0, 0.0, 1), (0.1, 0.0, 1), (0.1, 0.25, 1), (0.1, 0.25, 2), (0.3, 0.5, 1)):
    q = [[0, lam * (1 - s) + f * lam, lam * s], [mu, 0, lam], [0, crews * mu * (1 - s), 0]]
    wrong = [[0, lam + f * lam, 0], [mu, 0, lam], [0, crews * mu, 0]]
    check(f"standby s={s} idle={f} crews={crews}", a.standby(lam, mu, s, f, crews), 1 - ctmc(q)[2],
          alt=(1 - ctmc(wrong)[2]) if s else None)
check("series 0.9 x 0.8", network([unit("A", 90), unit("B", 40)],
      [edge("e1", "in", "m", 100, ["A"]), edge("e2", "m", "out", 100, ["B"])]), 0.72)
check("parallel 0.9 | 0.8", network([unit("A", 90), unit("B", 40)],
      [edge("e1", "in", "out", 100, ["A"]), edge("e2", "in", "out", 100, ["B"])]), 0.98)
three = [unit(k, 90) for k in "DEF"]
check("2oo3 voting 0.9", network(three + [unit("C", requires=list("DEF"), requires_k=2)],
      [edge("c", "in", "out", 100, ["C"])]), 0.972, alt=0.999)
check("shared utility under redundant trains", network(
    [unit("PWR", 90), unit("T1", requires=["PWR"]), unit("T2", requires=["PWR"])],
    [edge("a", "in", "out", 100, ["T1"]), edge("b", "in", "out", 100, ["T2"])]), 0.9, alt=0.99)
print("Reference verification ·", time.strftime("%Y-%m-%d %H:%M %Z"))
print("Tolerance: |mean - expected| < 4 SE + 0.0015 start-up bias allowance (system starts all-up).")
print("\n".join(rows))
if any("FAIL" in r or "NOT rejected" in r for r in rows):
    raise SystemExit(1)
