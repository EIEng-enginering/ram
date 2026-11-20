"""WP6: onshore example, independent utility reference case, report agreement, repeatability, awkward paths."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from rammodel.example import (UTILITY_REFERENCE_EXPECTED, UTILITY_REFERENCE_NO_DEPENDENCY, onshore,
                              utility_reference)
from rammodel.reporting import export
from rammodel.simulation import Simulator
from rammodel.storage import open_case
from rammodel.study import calculate, current_model, save_model, save_run

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UtilityReference(unittest.TestCase):
    def test_hand_calculation(self):
        # 0.99 * (0.95^2 + 2*0.95*0.05*0.6), written out independently of example.py.
        self.assertAlmostEqual(UTILITY_REFERENCE_EXPECTED, 0.949905)
        sim = Simulator(utility_reference())
        x = np.array([sim.replay(3, i)["efficiency"] for i in range(120)])
        se = x.std(ddof=1) / np.sqrt(len(x))
        self.assertLess(abs(x.mean() - 0.949905), 4 * se + 0.0015, (x.mean(), se))
        # Removing the shared utility dependency is measurably optimistic (false redundancy).
        free = deepcopy(utility_reference())
        for asset in free["assets"]:
            asset.pop("requires", None)
        y = np.array([Simulator(free).replay(3, i)["efficiency"] for i in range(120)])
        self.assertLess(abs(y.mean() - UTILITY_REFERENCE_NO_DEPENDENCY), 4 * y.std(ddof=1) / np.sqrt(120) + 0.0015)
        self.assertGreater(y.mean(), x.mean())


class Onshore(unittest.TestCase):
    def test_conservation_periods_and_repeatability(self):
        sim = Simulator(onshore())
        a, b = sim.replay(42, 3), Simulator(onshore()).replay(42, 3)
        self.assertEqual(a, b)
        self.assertLess(abs(a["balance"]["residual"]), 1e-6)
        self.assertEqual(sorted(a["years"]), ["2027"])
        self.assertEqual(len(a["periods"]), 12)
        self.assertAlmostEqual(sum(p["delivered"] for p in a["periods"].values()), a["delivered"], places=5)
        # Demand schedule 100/90/100 m3/h over 2160/4392/2208 h.
        self.assertAlmostEqual(a["contract"], 100 * 2160 + 90 * 4392 + 100 * 2208)

    def test_reports_agree_in_awkward_path(self):
        verify = load_tool("verify_reports")
        with TemporaryDirectory(prefix="RAM & Ünïcode Δ ") as folder:
            folder = Path(folder) / "Onshore case & copy ü"
            folder.mkdir()
            model = onshore()
            run = calculate(model, seed=9, initial=4, maximum=4)
            again = calculate(model, seed=9, initial=4, maximum=4)
            self.assertEqual(run["result"]["metrics"], again["result"]["metrics"])
            with open_case(folder / "Onshore ü & Δ.ramcase") as db:
                save_model(db, model)
                save_run(db, run)
                files = export(db, run["id"], folder / "Reports Δ")
            with open_case(folder / "Onshore ü & Δ.ramcase") as db:
                self.assertEqual(current_model(db)[0], model)
            count, problems = verify.check(next((folder / "Reports Δ").glob("ram_*.json")))
            self.assertEqual(problems, [])
            self.assertGreaterEqual(count, 9)


if __name__ == "__main__":
    unittest.main()
