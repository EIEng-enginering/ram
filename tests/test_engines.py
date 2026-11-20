from copy import deepcopy
import unittest

import numpy as np

from rammodel.analytics import cold_standby, component, hidden_periodic, independent_group, rbd, standby_pair
from rammodel.example import buffer_benchmark, double_buffer, offshore
from rammodel.simulation import Simulator, simulate
from rammodel.study import paired_compare


def simple():
    m = buffer_benchmark()
    del m["buffer"], m["maintenance"]
    m["hours"] = 500
    m["assets"][0]["modes"] = [{"id": "trip", "distribution": "exponential", "mtbf": 20,
                               "repair": 2, "logistics": 0, "mobilisation": 0, "loss": 1}]
    return m


class AnalysisTests(unittest.TestCase):
    def test_known_answers(self):
        self.assertAlmostEqual(component(90, 10), .9)
        self.assertAlmostEqual(independent_group("series", [.9, .8]), .72)
        self.assertAlmostEqual(independent_group("parallel", [.9, .8]), .98)
        self.assertAlmostEqual(independent_group("kofn", [.9] * 3, 2), .972)
        self.assertAlmostEqual(cold_standby(.1, .5), standby_pair(.1, 0, .5))
        self.assertLess(standby_pair(.1, .05, .5, .15), cold_standby(.1, .5))
        approx, exact = hidden_periodic(.00001, 10)
        self.assertAlmostEqual(approx, .00005)
        self.assertLess(abs(approx - exact), 2e-9)
        with self.assertRaises(ValueError):
            rbd({"kind": "parallel", "children": ["A", "A"]}, {"A": .9})

    def test_exact_cover_and_draw_limit(self):
        model = buffer_benchmark()
        run = Simulator(model).replay(40, trace=True)
        self.assertAlmostEqual(run["shortfall"], 0)
        self.assertAlmostEqual(run["buffer_end"], 0)
        model["buffer"]["draw"] = 75
        run = Simulator(model).replay(40)
        self.assertAlmostEqual(run["shortfall"], 150)
        self.assertAlmostEqual(run["buffer_end"], 150)

    def test_partial_capacity(self):
        model = buffer_benchmark()
        del model["buffer"]
        model["assets"].append({"id": "second", "modes": [], "explicit_no_failures": True})
        model["edges"][0]["capacity"] = 50
        model["edges"].append({"id": "parallel", "from": "feed", "to": "tank", "capacity": 50, "assets": ["second"]})
        result = Simulator(model).replay(2)
        self.assertAlmostEqual(result["shortfall"], 6 * 50)

    def test_repeatability_and_reference(self):
        sim = Simulator(simple())
        self.assertEqual(sim.replay(12, 4, True), sim.replay(12, 4, True))
        result = simulate(sim, 55, 700, 700)
        low, high = result["metrics"]["efficiency"]["ci95"]
        self.assertLessEqual(low, component(20, 2))
        self.assertGreaterEqual(high, component(20, 2))

    def test_offshore_replay_and_comparison(self):
        model = offshore()
        first = Simulator(model).replay(42, trace=True)
        self.assertGreater(len(first["intervals"]), 3)
        self.assertAlmostEqual(first["shortfall"], sum(first["loss_groups"].values()))
        # Independent arithmetic from the fixed-seed outage timeline. Three
        # single-train outages exhaust 600 m³ and each leave 345 m³ short.
        manual_loss = (3 * 345 + 45 * (506.8532684970448 - 486) +
                       100 * (633.6387298657016 - 626.1281335144752) +
                       45 * (1054.3500411738125 - 1054.1602501898199) +
                       100 * 19 + 165)
        self.assertAlmostEqual(first["shortfall"], manual_loss, places=7)
        self.assertAlmostEqual(first["efficiency"], 1 - manual_loss / 240000, places=10)
        compared = paired_compare(model, double_buffer(model), 42, 40)
        self.assertGreaterEqual(compared["difference"]["mean"], 0)

    def test_unsupported_and_missing_inputs(self):
        model = simple()
        broken = deepcopy(model)
        broken["assets"][0]["modes"] = []
        broken["assets"][0].pop("explicit_no_failures")
        with self.assertRaises(ValueError):
            Simulator(broken)
        model["standby"] = []
        with self.assertRaises(ValueError):
            Simulator(model)

    def test_spare_and_crew_keep_busy_fraction_bounded(self):
        model = offshore()
        for i in range(15):
            x = Simulator(model).replay(42, i, True)
            self.assertTrue(0 <= x["crew_utilisation"] <= 1)
            self.assertTrue(np.isfinite(x["efficiency"]))

    def test_standby_simulation_against_markov(self):
        model = simple()
        unit = model["assets"][0]
        unit["modes"] = []
        unit["standby_pair"] = {"active_mtbf": 20, "idle_mtbf": None,
                                "repair_mean": 5, "switch_failure": 0}
        sim = Simulator(model)
        n = 1000
        mean = sum(sim.replay(73, i)["efficiency"] for i in range(n)) / n
        self.assertAlmostEqual(mean, cold_standby(.05, .2), delta=.005)

    def test_zero_observed_failure_has_upper_uncertainty(self):
        from rammodel.analytics import constant_rate_estimate
        estimate = constant_rate_estimate(0, 10000)
        self.assertEqual(estimate["rate_per_h"], 0)
        self.assertGreater(estimate["interval_per_h"][1], 0)

    def test_utility_service_dependency_vote(self):
        model = simple()
        model["assets"][0]["modes"] = []
        model["assets"][0]["explicit_no_failures"] = True
        model["assets"][0]["requires"] = ["G1", "G2", "G3"]
        model["assets"][0]["requires_k"] = 2
        for name in ("G1", "G2", "G3"):
            model["assets"].append({"id": name, "modes": [], "explicit_no_failures": True})
        model["hours"] = 20
        model["volume_unit"] = "MWh"
        model["maintenance"] = [{"asset": "G1", "start": 2, "end": 7},
                                {"asset": "G2", "start": 5, "end": 10}]
        run = Simulator(model).replay(1)
        self.assertAlmostEqual(run["shortfall"], 200)
        self.assertAlmostEqual(run["efficiency"], .9)
