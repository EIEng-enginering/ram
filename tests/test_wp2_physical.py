"""WP2 acceptance: structure hand checks, routing, shared utilities, inventory
conservation, recycles, editing/undo/audit.

Expected numbers are derived by hand in the comments (independent of the engine).
Statistical comparisons use 4 standard errors plus a stated start-up bias bound.
"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from rammodel.analytics import component, independent_group, rbd
from rammodel.editing import BaselineChangeError, ModelEditor
from rammodel.example import buffer_benchmark
from rammodel.simulation import Simulator
from rammodel.storage import open_case
from rammodel.study import current_model, review_model, revisions


def unit(key, mtbf=None, mttr=10.0, **extra):
    modes = [] if mtbf is None else [{"id": "trip", "distribution": "exponential", "mtbf": mtbf, "loss": 1.0,
                                      "logistics": 0.0, "mobilisation": 0.0, "repair": mttr,
                                      "repair_distribution": "exponential"}]
    return {"id": key, "modes": modes, **({"explicit_no_failures": True} if mtbf is None else {}), **extra}


def network(assets, edges, hours=20000.0, target=100.0, **extra):
    return {"name": "hand check", "source": "in", "sink": "out", "target": target, "hours": hours,
            "volume_unit": "m3", "assets": assets, "edges": edges, **extra}


def edge(key, a, b, cap, assets, **extra):
    return {"id": key, "from": a, "to": b, "capacity": cap, "assets": assets, **extra}


def mean_efficiency(model, n=200, seed=11):
    sim = Simulator(model)
    x = np.array([sim.replay(seed, i)["efficiency"] for i in range(n)])
    return x.mean(), x.std(ddof=1) / np.sqrt(n)


class StructureHandChecks(unittest.TestCase):
    def test_analytic_nested_tree(self):
        # series(A, parallel(B, C), 2oo3(D, E, F)) = .95 * (1 - .1*.2) * (3*.81*.1 + .729)
        tree = {"kind": "series", "children": ["A", {"kind": "parallel", "children": ["B", "C"]},
                                                {"kind": "kofn", "k": 2, "children": ["D", "E", "F"]}]}
        values = {"A": .95, "B": .9, "C": .8, "D": .9, "E": .9, "F": .9}
        self.assertAlmostEqual(rbd(tree, values), .95 * .98 * .972, places=12)
        self.assertAlmostEqual(.95 * .98 * .972, 0.904932, places=12)

    def check(self, model, expected, bias=0.0015):
        mean, se = mean_efficiency(model)
        self.assertLess(abs(mean - expected), 4 * se + bias, (mean, se, expected))

    def test_flow_series_parallel_kofn_nested_match_algebra(self):
        a, b = unit("A", 90), unit("B", 40)        # 0.9 and 0.8 (MTTR 10 h)
        self.assertAlmostEqual(component(90, 10), .9)
        self.check(network([a, b], [edge("e1", "in", "m", 100, ["A"]), edge("e2", "m", "out", 100, ["B"])]), .72)
        self.check(network([a, b], [edge("e1", "in", "out", 100, ["A"]), edge("e2", "in", "out", 100, ["B"])]), .98)
        three = [unit(k, 90) for k in "DEF"]
        # Capacity arrangement 3 x 50 against 100: full rate with >= 2 up, half rate with exactly 1 up.
        # E = P(>=2) + 0.5 * P(1) = 0.972 + 0.5 * 3 * 0.9 * 0.1**2 = 0.9855 (not the 2oo3 success value).
        self.check(network(three, [edge(f"e{k}", "in", "out", 50, [k]) for k in "DEF"]), .9855)
        # 2oo3 success logic (voting dependency): availability 3 * .9**2 * .1 + .9**3 = 0.972.
        voter = unit("C", requires=["D", "E", "F"], requires_k=2)
        self.check(network(three + [voter], [edge("c", "in", "out", 100, ["C"])]), .972)
        nested = [unit("S", 190), a, b]             # S: 190/(190+10) = .95
        self.check(network(nested, [edge("s", "in", "m", 100, ["S"]), edge("p1", "m", "out", 100, ["A"]),
                                    edge("p2", "m", "out", 100, ["B"])]), .95 * .98)

    def test_shared_utility_removes_false_redundancy(self):
        trains = [unit("PWR", 90), unit("T1", requires=["PWR"]), unit("T2", requires=["PWR"])]
        model = network(trains, [edge("a", "in", "out", 100, ["T1"]), edge("b", "in", "out", 100, ["T2"])])
        # Redundant trains, one shared power supply: system availability equals power's 0.9, not 0.99.
        self.check(model, .9)
        deterministic = network([unit("PWR"), unit("T1", requires=["PWR"]), unit("T2", requires=["PWR"])],
                                [edge("a", "in", "out", 100, ["T1"]), edge("b", "in", "out", 100, ["T2"])],
                                hours=20, maintenance=[{"asset": "PWR", "start": 2, "end": 7}])
        self.assertAlmostEqual(Simulator(deterministic).replay(1)["shortfall"], 500)


class Routing(unittest.TestCase):
    def test_reroute_by_priority_after_branch_outage(self):
        model = network([unit("P1"), unit("P2")],
                        [edge("primary", "in", "out", 100, ["P1"], priority=1),
                         edge("backup", "in", "out", 100, ["P2"], priority=2)],
                        hours=10, maintenance=[{"asset": "P1", "start": 2, "end": 5}])
        run = Simulator(model).replay(0, trace=True)
        self.assertAlmostEqual(run["shortfall"], 0)
        by_time = {(i["start"], i["end"]): i["edge_flow"] for i in run["intervals"]}
        self.assertAlmostEqual(by_time[(0, 2)]["primary"], 100)
        self.assertAlmostEqual(by_time[(0, 2)]["backup"], 0)
        self.assertAlmostEqual(by_time[(2, 5)]["primary"], 0)
        self.assertAlmostEqual(by_time[(2, 5)]["backup"], 100)
        self.assertAlmostEqual(by_time[(5, 10)]["primary"], 100)

    def test_unsupported_topologies_reported(self):
        base = network([unit("P")], [edge("a", "in", "m", 100, ["P"]), edge("b", "m", "out", 100, []),
                                     edge("c", "m", "n", 50, []), edge("d", "n", "m", 50, [])], hours=10)
        with self.assertRaisesRegex(ValueError, "Recycle"):
            Simulator(base)
        products = deepcopy(base)
        products["products"] = []
        with self.assertRaisesRegex(ValueError, "products"):
            Simulator(products)
        bad = network([unit("P")], [edge("a", "in", "out", 100, ["P"])], hours=10,
                      buffer={"node": "out", "capacity": 10, "initial": 0, "fill": 1, "draw": 1})
        with self.assertRaisesRegex(ValueError, "buffer node"):
            Simulator(bad)

    def test_declared_recycle_is_solved_without_spurious_circulation(self):
        model = network([unit("P")], [edge("a", "in", "m", 100, ["P"]), edge("b", "m", "out", 100, []),
                                      edge("c", "m", "n", 50, []), edge("d", "n", "m", 50, [])],
                        hours=10, recycle_edges=["d"])
        run = Simulator(model).replay(0, trace=True)
        self.assertAlmostEqual(run["shortfall"], 0)
        flows = run["intervals"][0]["edge_flow"]
        self.assertAlmostEqual(flows["c"], 0)
        self.assertAlmostEqual(flows["d"], 0)
        self.assertLess(abs(run["balance"]["residual"]), 1e-6)

    def test_yield_loss_balance(self):
        # 10 % loss on the inlet: supply = 100 / 0.9 per hour; loss = supply - delivery.
        model = network([unit("P")], [edge("a", "in", "m", 200, ["P"], **{"yield": 0.9}),
                                      edge("b", "m", "out", 100, [])], hours=9, feed=200)
        run = Simulator(model).replay(0)
        self.assertAlmostEqual(run["balance"]["supply"], 9 * 100 / 0.9, places=6)
        self.assertAlmostEqual(run["balance"]["yield_loss"], 9 * 100 / 0.9 - 900, places=6)
        self.assertLess(abs(run["balance"]["residual"]), 1e-6)


class Inventory(unittest.TestCase):
    def two_tanks(self, t1_initial=150.0):
        # wells -in(P1, 120)-> t1 -mid(P2, 120)-> t2 -out(100)-> sales ; feed 120, target 100.
        return {"name": "two buffers", "source": "wells", "sink": "sales", "target": 100, "feed": 120,
                "hours": 24, "volume_unit": "m3",
                "assets": [unit("P1"), unit("P2")],
                "edges": [edge("in", "wells", "t1", 120, ["P1"]), edge("mid", "t1", "t2", 120, ["P2"]),
                          edge("out", "t2", "sales", 100, [])],
                "buffers": [{"id": "T1", "node": "t1", "capacity": 300, "initial": t1_initial, "fill": 20, "draw": 100},
                            {"id": "T2", "node": "t2", "capacity": 200, "initial": 200, "fill": 20, "draw": 100}],
                "maintenance": [{"asset": "P1", "start": 10, "end": 14}, {"asset": "P2", "start": 12, "end": 16}]}

    def test_two_buffer_conservation_and_hand_trace(self):
        # Hand trace: T1 fills 20/h from 150 to 300 at 7.5 h. P1 down at 10 h: T2 (full) supplies
        # 100/h and is empty at 12 h exactly when P2 also stops; nothing reaches sales 12-16 h
        # (400 m3 short). From 16 h, out = 100 and T2 refills at 20/h: 160 m3 at 24 h. T1 stays 300.
        run = Simulator(self.two_tanks()).replay(0, trace=True)
        self.assertAlmostEqual(run["shortfall"], 400, places=6)
        self.assertAlmostEqual(run["delivered"], 2000, places=6)
        self.assertAlmostEqual(run["buffer_levels"]["T1"], 300, places=6)
        self.assertAlmostEqual(run["buffer_levels"]["T2"], 160, places=6)
        self.assertAlmostEqual(run["balance"]["supply"], 120 * 7.5 + 100 * 2.5 + 120 * 8, places=6)
        self.assertLess(abs(run["balance"]["residual"]), 1e-6)
        for b, (start, end) in (("T1", (150, 300)), ("T2", (200, 160))):
            flows = run["balance"][f"buffer:{b}:in"] - run["balance"][f"buffer:{b}:out"]
            self.assertAlmostEqual(start + flows, end, places=6)

    def test_initial_inventory_at_both_limits(self):
        empty = self.two_tanks(t1_initial=0)
        empty["buffers"][1]["initial"] = 0
        empty["maintenance"] = [{"asset": "P1", "start": 0, "end": 3}]
        run = Simulator(empty).replay(0)
        # Empty tanks and no inlet for 3 h: 300 m3 short; afterwards both tanks fill at 20/h total.
        self.assertAlmostEqual(run["shortfall"], 300, places=6)
        self.assertLess(abs(run["balance"]["residual"]), 1e-6)
        full = self.two_tanks(t1_initial=300)
        full["maintenance"] = []
        run = Simulator(full).replay(0)
        self.assertAlmostEqual(run["buffer_levels"]["T1"], 300)
        self.assertAlmostEqual(run["buffer_levels"]["T2"], 200)
        self.assertAlmostEqual(run["shortfall"], 0)

    def test_exact_six_hour_cover_retained(self):
        run = Simulator(buffer_benchmark()).replay(40, trace=True)
        self.assertAlmostEqual(run["shortfall"], 0)
        self.assertAlmostEqual(run["buffer_end"], 0)


class Editing(unittest.TestCase):
    def test_edit_undo_redo_reload_and_audit(self):
        with TemporaryDirectory(prefix="RAM & Edit ") as folder:
            path = Path(folder) / "edit.ramcase"
            base = buffer_benchmark()
            editor = ModelEditor(base, validator=Simulator)
            seen = []
            editor.listeners.append(seen.append)
            editor.select("assets/P")
            self.assertEqual(seen, ["assets/P"])
            editor.apply({"op": "add_asset", "id": "Q", "explicit_no_failures": True}, "Engineer")
            editor.apply({"op": "add_edge", "id": "bypass", "from": "feed", "to": "tank", "capacity": 50,
                          "assets": ["Q"], "priority": 2}, "Engineer")
            editor.apply({"op": "set", "target": ["edges", "in", "priority"], "value": 1}, "Engineer")
            self.assertEqual(editor.issues(), [])
            # bypass covers half the outage: hand result 6 h * 0 short because the tank already covers 6 h.
            self.assertAlmostEqual(Simulator(editor.model).replay(0)["shortfall"], 0)
            editor.undo("Engineer")
            self.assertNotIn("priority", editor.model["edges"][0])
            editor.redo("Engineer")
            self.assertEqual(editor.model["edges"][0]["priority"], 1)
            with self.assertRaises(ValueError):
                editor.apply({"op": "remove_asset", "id": "Q"})   # still used by an edge
            self.assertEqual(len(editor.change_list()), 5)
            with open_case(path) as db:
                fingerprint = editor.save(db, "Engineer", "Add bypass")
            with open_case(path) as db:
                model, stored, *_ = current_model(db)
                self.assertEqual(stored, fingerprint)
                self.assertEqual(model, editor.model)
                actions = [r[0] for r in db.execute("SELECT action FROM review_log ORDER BY id")]
                self.assertEqual(actions.count("model edit"), 3)
                self.assertEqual(actions.count("model undo"), 1)
                self.assertEqual(revisions(db)[-1]["note"], "Add bypass")

    def test_approved_baseline_requires_confirmation(self):
        with TemporaryDirectory(prefix="RAM & Edit ") as folder:
            path = Path(folder) / "approved.ramcase"
            model = buffer_benchmark()
            from rammodel.study import save_model
            with open_case(path) as db:
                sha = save_model(db, model)
                review_model(db, "Reviewer", sha)
            editor = ModelEditor(model, approved_hash=sha)
            with self.assertRaises(BaselineChangeError):
                editor.apply({"op": "set", "target": ["edges", "out", "capacity"], "value": 90})
            editor.apply({"op": "set", "target": ["edges", "out", "capacity"], "value": 90}, confirm_baseline=True)
            with open_case(path) as db:
                editor.save(db, "Engineer")
                self.assertIsNone(current_model(db)[2])   # approval cleared on the new revision


if __name__ == "__main__":
    unittest.main()
