"""WP3 acceptance: availability references, independent CTMCs for explicit standby,
operating clocks, restoration, hidden-failure test downtime, common cause, calendar
attribution, deferral classification, weather policy, queues, schedules, economics.

Every expected value is derived in the comments or computed by an independent
formula/generator written in this file, never by calling the engine under test.
Monte Carlo checks use |mean - expected| < 4 standard errors + a stated start-up bias.
"""
from copy import deepcopy
from math import exp, gamma as G, log
import unittest

import numpy as np
from scipy.integrate import quad

from rammodel.analytics import component, hidden_periodic, independent_group
from rammodel.simulation import Simulator, simulate
from rammodel.study import calculate, no_failure_reference


def mode(mtbf, repair, **extra):
    return {"id": extra.pop("id", "trip"), "distribution": "exponential", "mtbf": mtbf, "loss": 1.0,
            "logistics": 0.0, "mobilisation": 0.0, "repair": repair, **extra}


def asset(key, *modes, **extra):
    return {"id": key, "modes": list(modes), **({} if modes else {"explicit_no_failures": True}), **extra}


def line(assets, edges, hours, target=100.0, **extra):
    return {"name": "wp3", "source": "in", "sink": "out", "target": target, "hours": hours, "volume_unit": "m3",
            "assets": assets, "edges": edges, **extra}


def e(key, a, b, cap, assets=(), **extra):
    return {"id": key, "from": a, "to": b, "capacity": cap, "assets": list(assets), **extra}


def mc(model, n=200, seed=5):
    sim = Simulator(model)
    x = np.array([sim.replay(seed, i)["efficiency"] for i in range(n)])
    return x.mean(), x.std(ddof=1) / np.sqrt(n)


def ctmc(q):
    q = np.array(q, dtype=float)
    np.fill_diagonal(q, -q.sum(axis=1))
    a = np.vstack([q.T, np.ones(len(q))])
    b = np.zeros(len(q) + 1)
    b[-1] = 1
    return np.linalg.lstsq(a, b, rcond=None)[0]


class Availability(unittest.TestCase):
    def close(self, model, expected, bias=0.0015, n=200):
        mean, se = mc(model, n)
        self.assertLess(abs(mean - expected), 4 * se + bias, (mean, se, expected))

    def test_reference_values(self):
        self.assertAlmostEqual(component(90, 10), 0.9)
        self.assertAlmostEqual(independent_group("series", [.9, .8]), .72)
        self.assertAlmostEqual(independent_group("parallel", [.9, .8]), .98)
        self.assertAlmostEqual(independent_group("kofn", [.9] * 3, 2), .972)
        # Simulation of the single repairable unit (exponential repair) against MTBF/(MTBF+MTTR).
        self.close(line([asset("A", mode(90, 10, repair_distribution="exponential"))],
                        [e("a", "in", "out", 100, ["A"])], 20000), 0.9)

    def standby(self, lam, mu, s, f, crews):
        pump = lambda k: asset(k, mode(1 / lam, 1 / mu, exposure="operating", idle_factor=f,
                                       repair_distribution="exponential"),
                               *([{"id": "start", "distribution": "demand", "probability": s, "loss": 1.0,
                                   "logistics": 0.0, "mobilisation": 0.0, "repair": 1 / mu,
                                   "repair_distribution": "exponential"}] if s else []))
        return line([pump("PA"), pump("PB")], [e("a", "in", "out", 100, ["PA"]), e("b", "in", "out", 100, ["PB"])],
                    20000, crews=crews, standby_groups=[{"id": "pumps", "members": ["PA", "PB"], "running": 1}])

    def test_explicit_standby_against_independent_ctmc(self):
        lam, mu = 1 / 100, 1 / 20
        for s, f, crews in ((0.0, 0.0, 1), (0.1, 0.0, 1), (0.1, 0.25, 1), (0.1, 0.25, 2), (0.3, 0.5, 1)):
            # States: 0 both healthy (one running), 1 one failed, 2 both failed.
            q = [[0, lam * (1 - s) + f * lam, lam * s],
                 [mu, 0, lam],
                 [0, crews * mu * (1 - s), 0]]
            expected = 1 - ctmc(q)[2]
            with self.subTest(s=s, f=f, crews=crews):
                self.close(self.standby(lam, mu, s, f, crews), expected, n=150)
        # Cold, perfect switch, one crew equals the closed form (1 + r) / (1 + r + r^2), r = lam/mu.
        r = lam / mu
        self.assertAlmostEqual(1 - ctmc([[0, lam, 0], [mu, 0, lam], [0, mu, 0]])[2], (1 + r) / (1 + r + r * r))

    def test_common_cause_beta_factor(self):
        lam, beta, mu = 1 / 200, 0.1, 1 / 10
        ind = lam * (1 - beta)
        model = line([asset("A", mode(1 / ind, 10, repair_distribution="exponential")),
                      asset("B", mode(1 / ind, 10, repair_distribution="exponential"))],
                     [e("a", "in", "out", 100, ["A"]), e("b", "in", "out", 100, ["B"])], 20000,
                     common_cause=[{"id": "beta", "assets": ["A", "B"], "mtbf": 1 / (beta * lam), "loss": 1.0,
                                    "logistics": 0.0, "mobilisation": 0.0, "repair": 10.0,
                                    "repair_distribution": "exponential"}])
        a_i = mu / (mu + ind)
        a_c = mu / (mu + beta * lam)
        self.close(model, a_c * (1 - (1 - a_i) ** 2))
        # Without the shock the same pair would be optimistic.
        self.assertGreater(1 - (1 - mu / (mu + lam)) ** 2, a_c * (1 - (1 - a_i) ** 2))


class Clocks(unittest.TestCase):
    def test_unused_operating_exposure_asset_never_ages(self):
        backup = mode(5, 1, exposure="operating")
        model = line([asset("P"), asset("S", backup)],
                     [e("p", "in", "out", 100, ["P"], priority=1), e("s", "in", "out", 100, ["S"], priority=2)], 1000)
        self.assertEqual(Simulator(model).replay(3)["failures"]["S/trip"], 0)
        model["assets"][1]["modes"][0]["exposure"] = "calendar"
        self.assertGreater(Simulator(model).replay(3)["failures"]["S/trip"], 50)

    def test_planned_outage_shifts_operating_failure_exactly(self):
        unit = asset("A", mode(400, 1, exposure="operating"))
        base = line([unit], [e("a", "in", "out", 100, ["A"])], 2000)
        first = lambda m: next(x["hour"] for x in Simulator(m).replay(9, trace=True)["events"] if x["event"] == "fail_op")
        t0 = first(base)
        self.assertGreater(t0, 30)
        delayed = deepcopy(base)
        delayed["maintenance"] = [{"asset": "A", "start": 10, "end": 35}]
        self.assertAlmostEqual(first(delayed), t0 + 25, places=9)

    def test_as_bad_as_old_is_minimal_repair(self):
        # Minimal repair of a Weibull(eta=100, k=2) item with zero repair time is an NHPP:
        # E[N(300)] = (300/100)^2 = 9. As-good-as-new gives far fewer (renewal ~ 3).
        bad = mode(None, 0, distribution="weibull", scale=100.0, shape=2.0, restoration="as_bad_as_old")
        bad.pop("mtbf")
        model = line([asset("W", bad)], [e("w", "in", "out", 100, ["W"])], 300)
        sim = Simulator(model)
        counts = np.array([sim.replay(1, i)["failures"]["W/trip"] for i in range(2000)])
        self.assertLess(abs(counts.mean() - 9), 4 * counts.std(ddof=1) / np.sqrt(2000))
        model["assets"][0]["modes"][0]["restoration"] = "as_good_as_new"
        sim = Simulator(model)
        renewal = np.mean([sim.replay(1, i)["failures"]["W/trip"] for i in range(2000)])
        mean_life = 100 * G(1.5)
        self.assertLess(renewal, 300 / mean_life + 0.5)


class Hidden(unittest.TestCase):
    def test_proof_test_downtime_matches_exact_periodic_formula(self):
        lam, tau, d = 1 / 500, 100.0, 5.0
        # Renewal at each test (repair 0): down = test d plus failure-to-next-test time.
        # U = 1 - (exp(-lam d) - exp(-lam tau)) / (lam tau)   (derived in docs/METHODS_IMPLEMENTED.md)
        expected = (exp(-lam * d) - exp(-lam * tau)) / (lam * tau)
        hidden = mode(1 / lam, 0.0, detection="hidden", proof=tau, test_duration=d)
        model = line([asset("H", hidden)], [e("h", "in", "out", 100, ["H"])], 10000)
        mean, se = mc(model, 300)
        self.assertLess(abs(mean - expected), 4 * se + 1e-4, (mean, expected))
        # d = 0 reduces to the existing exact periodic result.
        self.assertAlmostEqual(1 - (1 - exp(-lam * tau)) / (lam * tau), hidden_periodic(lam, tau)[1], places=12)


class Deterministic(unittest.TestCase):
    def ccf(self, times, repair, assets=("A", "Z"), **extra):
        return {"id": f"shock{times}", "assets": list(assets), "times": list(times), "loss": 1.0,
                "logistics": 0.0, "mobilisation": 0.0, "repair": repair, **extra}

    def test_deterministic_common_cause_outage(self):
        model = line([asset("A"), asset("B")], [e("a", "in", "out", 100, ["A"]), e("b", "in", "out", 100, ["B"])],
                     200, common_cause=[self.ccf([100], 10, ("A", "B"))])
        run = Simulator(model).replay(0)
        self.assertAlmostEqual(run["shortfall"], 1000)
        self.assertEqual(run["failures"]["CCF:shock[100]"], 1)

    def test_month_end_attribution_and_annual_rollup(self):
        model = line([asset("A")], [e("a", "in", "out", 100, ["A"])], 72,
                     calendar_start="2026-12-31T00:00", maintenance=[{"asset": "A", "start": 12, "end": 36}],
                     closed_access=[])
        run = Simulator(model).replay(0)
        p = run["periods"]
        self.assertAlmostEqual(p["2026-12"]["shortfall"], 1200)   # 12:00-24:00 on 31 Dec
        self.assertAlmostEqual(p["2027-01"]["shortfall"], 1200)   # 00:00-12:00 on 1 Jan
        self.assertAlmostEqual(p["2026-12"]["demand"], 2400)
        self.assertAlmostEqual(p["2027-01"]["demand"], 4800)
        self.assertAlmostEqual(run["years"]["2026"]["delivered"], 1200)
        self.assertAlmostEqual(sum(v["delivered"] for v in p.values()), run["delivered"])
        self.assertAlmostEqual(sum(v["shortfall"] for v in p.values()), run["shortfall"])
        self.assertAlmostEqual(sum(v["demand"] for v in p.values()), run["contract"])

    def deferral(self, window, hours):
        return line([asset("A")], [e("a", "in", "out", 120, ["A"])], hours, feed=120,
                    maintenance=[{"asset": "A", "start": 10, "end": 20}],
                    deferral={"window_h": window, "recovery_rate": 20})

    def test_delayed_recovery_lost_and_deferred(self):
        # 10 h outage -> 1000 short at 100/h. Spare capacity 20/h recovers it in 50 h (20-70 h).
        run = Simulator(self.deferral(100, 100)).replay(0)
        self.assertAlmostEqual((run["recovered"], run["lost"], run["deferred"]), (1000, 0, 0))
        self.assertAlmostEqual(run["delivered"], 100 * 100)
        # Window 30 h from the start of the shortfall (10 h): 400 recovered by 40 h, 600 lost at 40 h.
        run = Simulator(self.deferral(30, 100)).replay(0)
        self.assertAlmostEqual(run["recovered"], 400)
        self.assertAlmostEqual(run["lost"], 600)
        # Horizon 50 h with a long window: 600 recovered, 400 still potentially deferred.
        run = Simulator(self.deferral(100, 50)).replay(0)
        self.assertAlmostEqual((run["recovered"], run["lost"], run["deferred"]), (600, 0, 400))
        self.assertAlmostEqual(run["shortfall"], run["recovered"] + run["lost"] + run["deferred"])

    def test_overlapping_outages_counted_once(self):
        model = line([asset("A"), asset("B")], [e("a", "in", "m", 100, ["A"]), e("b", "m", "out", 100, ["B"])], 10,
                     maintenance=[{"asset": "A", "start": 2, "end": 6}, {"asset": "B", "start": 4, "end": 8}])
        run = Simulator(model).replay(0)
        self.assertAlmostEqual(run["shortfall"], 600)
        self.assertEqual(run["loss_groups"], {"A/planned": 200.0, "A/planned + B/planned": 200.0,
                                              "B/planned": 200.0})

    def weather(self, policy, failure_time):
        return line([asset("A"), asset("Z")], [e("a", "in", "out", 100, ["A"])], 100,
                    common_cause=[self.ccf([failure_time], 8)], closed_access=[[12, 20]], weather_policy=policy)

    def test_weather_policies(self):
        # Failure at 10 h, 8 h repair started at 10 h. Access closed 12-20 h.
        self.assertAlmostEqual(Simulator(self.weather("continue", 10)).replay(0)["shortfall"], 800)  # restored 18 h
        self.assertAlmostEqual(Simulator(self.weather("suspend", 10)).replay(0)["shortfall"], 1600)  # 2 h + pause + 6 h -> 26 h
        # Failure during closure: repair starts at 20 h, restored 28 h -> 15 h down under either policy.
        self.assertAlmostEqual(Simulator(self.weather("continue", 13)).replay(0)["shortfall"], 1500)
        self.assertAlmostEqual(Simulator(self.weather("suspend", 13)).replay(0)["shortfall"], 1500)

    def test_simultaneous_events_and_crew_queue(self):
        # Maintenance ends at 10 h exactly when a shock starts a 5 h repair: one contiguous 15 h outage.
        model = line([asset("A"), asset("Z")], [e("a", "in", "out", 100, ["A"])], 50,
                     maintenance=[{"asset": "A", "start": 0, "end": 10}], common_cause=[self.ccf([10], 5)])
        self.assertAlmostEqual(Simulator(model).replay(0)["shortfall"], 1500)
        # Two independent shocks at 10 h on A and B in series, one crew: B waits, restored 20 h.
        queue = line([asset("A"), asset("B"), asset("Y"), asset("Z")],
                     [e("a", "in", "m", 100, ["A"]), e("b", "m", "out", 100, ["B"])], 50, crews=1,
                     common_cause=[self.ccf([10], 5, ("A", "Y")), {**self.ccf([10], 5, ("B", "Z")), "id": "second"}])
        self.assertAlmostEqual(Simulator(queue).replay(0)["shortfall"], 1000)
        queue["crews"] = 2
        self.assertAlmostEqual(Simulator(queue).replay(0)["shortfall"], 500)

    def test_zero_demand_period_and_schedules(self):
        model = line([asset("A")], [e("a", "in", "out", 100, ["A"])], 30,
                     demand_schedule=[[0, 100], [10, 0], [20, 100]],
                     maintenance=[{"asset": "A", "start": 12, "end": 18}])
        run = Simulator(model).replay(0)
        self.assertAlmostEqual(run["contract"], 2000)
        self.assertAlmostEqual(run["shortfall"], 0)
        self.assertAlmostEqual(run["efficiency"], 1.0)
        capped = line([asset("A")], [e("a", "in", "out", 100, ["A"])], 30,
                      capacity_schedule=[{"edge": "a", "start": 5, "end": 15, "capacity": 60}])
        self.assertAlmostEqual(Simulator(capped).replay(0)["shortfall"], 400)
        with self.assertRaisesRegex(ValueError, "efficiency is undefined"):
            Simulator(line([asset("A")], [e("a", "in", "out", 100, ["A"])], 30, demand_schedule=[[0, 0]]))

    def test_economics_from_entered_assumptions_only(self):
        econ = {"currency": "AUD", "cost_basis": "2026 real, synthetic", "source": "EXAMPLE assumption",
                "value_per_unit": 50.0, "discount_rate_per_year": 0.08}
        model = line([asset("A")], [e("a", "in", "out", 100, ["A"])], 8760,
                     maintenance=[{"asset": "A", "start": 4380, "end": 4390}], economics=econ)
        run = Simulator(model).replay(0)
        k = log(1.08) / 8760
        exact = quad(lambda t: 100 * 50 * exp(-k * t), 4380, 4390)[0]
        self.assertAlmostEqual(run["lost_value"], exact, places=4)
        broken = deepcopy(model)
        del broken["economics"]["currency"]
        with self.assertRaises(ValueError):
            Simulator(broken)

    def test_incomplete_inputs_reported(self):
        model = line([asset("A", {"id": "trip", "distribution": "exponential", "mtbf": 10, "loss": 1})],
                     [e("a", "in", "out", 100, ["A"])], 10)
        with self.assertRaisesRegex(ValueError, "Incomplete model input"):
            Simulator(model)

    def test_whole_case_conservation_and_reference_separation(self):
        model = self.deferral(30, 100)
        model["buffers"] = [{"id": "T", "node": "m", "capacity": 50, "initial": 25, "fill": 10, "draw": 50}]
        model["edges"] = [e("a", "in", "m", 120, ["A"]), e("b", "m", "out", 150)]
        model["calendar_start"] = "2027-03-31T20:00"
        run = Simulator(model).replay(0)
        self.assertLess(abs(run["balance"]["residual"]), 1e-6)
        p = run["periods"]
        self.assertAlmostEqual(sum(v["delivered"] for v in p.values()), run["delivered"], places=6)
        self.assertAlmostEqual(sum(v.get("lost", 0) for v in p.values()), run["lost"], places=6)
        record = calculate(model, seed=1, initial=2, maximum=2)
        self.assertAlmostEqual(record["basis"]["contractual_demand"], 10000)
        self.assertAlmostEqual(record["basis"]["no_failure_delivery"], no_failure_reference(model)["delivered"])
        self.assertIn("0.3 features", record["method_profile"])


class Statistics(unittest.TestCase):
    def test_zero_event_run_is_not_zero_risk(self):
        model = line([asset("A", mode(1e9, 1))], [e("a", "in", "out", 100, ["A"])], 10)
        result = simulate(Simulator(model), 1, 50, 50)
        self.assertEqual(result["diagnostics"]["replications_with_shortfall"], 0)
        self.assertIn("not evidence of zero risk", result["diagnostics"]["note"])
        self.assertAlmostEqual(result["diagnostics"]["shortfall_probability_upper_95"], 3 / 50)
        self.assertFalse(result["converged"])
        self.assertIn("zero sampled variance", result["stop_reason"])


if __name__ == "__main__":
    unittest.main()


class LegacyReproduction(unittest.TestCase):
    """0.2 models must replay bit-for-bit (values produced by the untouched 0.2 alpha source)."""

    def test_alpha_replays_identical(self):
        import json
        from pathlib import Path
        from rammodel.example import double_buffer, offshore, offshore_extended, separation_options
        ref = json.loads((Path(__file__).parent / "fixtures" / "alpha_0_2_reference_replays.json").read_text())
        models = {"offshore_extended": offshore_extended(), "offshore": offshore(),
                  "double_buffer": double_buffer(offshore_extended()),
                  "three_trains": separation_options(offshore_extended())[1]}
        for name, model in models.items():
            sim = Simulator(model)
            self.assertEqual(sim.features, [])
            self.assertEqual([sim.replay(42, i)["efficiency"] for i in range(60)], ref[name], name)
        intervals = Simulator(offshore()).replay(42, 0, True)["intervals"]
        self.assertEqual([[i["start"], i["end"], i["delivery"], i["buffer_end"], i["loss"]] for i in intervals],
                         ref["offshore_rep0_intervals"])
