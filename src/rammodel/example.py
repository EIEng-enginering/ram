"""Synthetic reference cases. These values are invented exclusively for testing."""
from copy import deepcopy

SOURCE = "EXAMPLE – synthetic offshore basis, 20 November 2026"


def offshore():
    def asset(key, mtbf=None, repair=0, required=(), spare=None):
        modes = [] if mtbf is None else [{"id": "trip", "distribution": "exponential", "mtbf": mtbf,
                                           "loss": 1.0, "logistics": 2.0, "mobilisation": 3.0, "repair": repair,
                                           **({"spare": spare} if spare else {})}]
        return {"id": key, "modes": modes, "requires": list(required),
                **({"explicit_no_failures": True} if mtbf is None else {})}

    def edge(key, a, b, capacity, equipment):
        return {"id": key, "from": a, "to": b, "capacity": capacity, "assets": equipment}

    assets = [asset("MANIFOLD"), asset("PWR-A", 2100, 12), asset("PWR-B", 2100, 12),
              asset("SEP-A", 1250, 16, ["PWR-A"]), asset("SEP-B", 1250, 16, ["PWR-B"]),
              asset("COMP", 1600, 14), asset("EXP-A", 1900, 14, spare="export"), asset("EXP-B", 1900, 14)]
    edges = [edge("feed", "wells", "manifold", 110, ["MANIFOLD"]),
             edge("train-A", "manifold", "tank", 55, ["SEP-A", "COMP"]),
             edge("train-B", "manifold", "tank", 55, ["SEP-B", "COMP"]),
             edge("export-A", "tank", "sales", 100, ["EXP-A"]),
             edge("export-B", "tank", "sales", 100, ["EXP-B"])]
    model = {"name": "Synthetic offshore module", "example": True, "basis": SOURCE, "source": "wells",
             "sink": "sales", "hours": 2400, "target": 100, "feed": 110, "volume_unit": "m3",
             "assets": assets, "edges": edges, "crews": 1, "spares": {"export": {"initial": 1, "lead": 96}},
             "buffer": {"node": "tank", "capacity": 600, "initial": 600, "fill": 10, "draw": 100},
             "closed_access": [[820, 844], [1080, 1100]],
             "maintenance": [{"asset": "COMP", "start": 480, "end": 486}],
             "provenance": {}}
    model["provenance"].update({f"assets/{a['id']}": SOURCE for a in assets})
    model["provenance"].update({f"edges/{e['id']}": SOURCE for e in edges})
    model["provenance"].update({f"modes/{a['id']}/{m['id']}": SOURCE for a in assets for m in a["modes"]})
    model["provenance"].update({f"dependencies/{a['id']}/{d}": SOURCE for a in assets for d in a["requires"]})
    model["provenance"].update({f"study/{k}": SOURCE for k in ("hours", "target", "feed", "crews", "spares",
                                                               "buffer", "closed_access", "maintenance")})
    return model


def buffer_benchmark():
    """A full 600 m³ tank covers exactly six hours at 100 m³/h."""
    return {"name": "Exact-cover synthetic benchmark", "example": True, "basis": SOURCE,
            "source": "feed", "sink": "sales", "target": 100, "hours": 12, "volume_unit": "m3",
            "edges": [{"id": "in", "from": "feed", "to": "tank", "capacity": 100, "assets": ["P"]},
                      {"id": "out", "from": "tank", "to": "sales", "capacity": 100}],
            "assets": [{"id": "P", "modes": [], "explicit_no_failures": True}],
            "buffer": {"node": "tank", "capacity": 600, "initial": 600, "fill": 100, "draw": 100},
            "maintenance": [{"asset": "P", "start": 2, "end": 8}],
            "provenance": {key: SOURCE for key in ("edges/in", "edges/out", "assets/P", "study/hours",
                                                    "study/target", "study/buffer", "study/maintenance")}}


def double_buffer(model):
    option = deepcopy(model)
    option["buffer"]["capacity"] *= 2
    option["name"] += " – larger tank"
    return option


def offshore_extended():
    model = offshore()
    model["name"] = "Synthetic offshore production module"
    model["assets"].append({"id": "PWR-C", "modes": [
        {"id": "trip", "distribution": "exponential", "mtbf": 2100, "loss": 1,
         "logistics": 2, "mobilisation": 3, "repair": 12}]})
    model["assets"].append({"id": "POWER-2OO3", "modes": [], "explicit_no_failures": True,
                            "requires": ["PWR-A", "PWR-B", "PWR-C"], "requires_k": 2})
    for asset in model["assets"]:
        if asset["id"].startswith(("SEP-", "EXP-")):
            for parent in asset["requires"]:
                model["provenance"].pop(f"dependencies/{asset['id']}/{parent}", None)
            asset["requires"] = ["POWER-2OO3"]
            model["provenance"][f"dependencies/{asset['id']}/POWER-2OO3"] = SOURCE
        if asset["id"] == "COMP":
            asset["modes"] = []
            asset["standby_pair"] = {"active_mtbf": 1600, "idle_mtbf": None,
                                     "repair_mean": 19, "switch_failure": 0.02}
            model["provenance"].pop("modes/COMP/trip")
    for parent in ("PWR-A", "PWR-B", "PWR-C"):
        model["provenance"][f"dependencies/POWER-2OO3/{parent}"] = SOURCE
    for key in ("assets/PWR-C", "assets/POWER-2OO3", "modes/PWR-C/trip", "standby/COMP"):
        model["provenance"][key] = SOURCE
    return model


def separation_options(model):
    one, three = deepcopy(model), deepcopy(model)
    one["edges"] = [e for e in one["edges"] if e["id"] != "train-B"]
    one["edges"][1]["capacity"] = 110
    one["assets"] = [a for a in one["assets"] if a["id"] != "SEP-B"]
    asset = deepcopy(next(a for a in three["assets"] if a["id"] == "SEP-B"))
    asset["id"] = "SEP-C"
    three["assets"].append(asset)
    edge = deepcopy(next(e for e in three["edges"] if e["id"] == "train-B"))
    edge["id"] = "train-C"
    edge["assets"] = ["SEP-C" if key == "SEP-B" else key for key in edge["assets"]]
    three["edges"].append(edge)
    for key in ("assets/SEP-C", "modes/SEP-C/trip", "dependencies/SEP-C/POWER-2OO3", "edges/train-C"):
        three["provenance"][key] = SOURCE
    return one, three


ONSHORE_SOURCE = "EXAMPLE – synthetic onshore basis, 20 November 2026 (method 0.3 features)"


def _mode(key, mtbf, repair, **extra):
    return {"id": key, "distribution": "exponential", "mtbf": mtbf, "loss": 1.0, "logistics": 0.0,
            "mobilisation": 0.0, "repair": repair, "repair_distribution": "exponential", **extra}


def _provenance(model, source):
    p = {f"assets/{a['id']}": source for a in model["assets"]}
    p.update({f"edges/{e['id']}": source for e in model["edges"]})
    p.update({f"modes/{a['id']}/{m['id']}": source for a in model["assets"] for m in a["modes"]})
    p.update({f"dependencies/{a['id']}/{d}": source for a in model["assets"] for d in a.get("requires", [])})
    p.update({f"study/{k}": source for k in model if k not in {"name", "example", "basis", "source", "sink",
                                                                "assets", "edges", "provenance", "volume_unit"}})
    return p


def utility_reference():
    """Independent utility reference case with a hand-calculable answer.

    GRID (A_g = 990/(990+10) = 0.99) is required by two compressors (A_c = 190/(190+10) = 0.95),
    each 60 units/h against a 100 units/h target. All clocks are calendar-time and repair crews
    are unlimited, so components are independent and
        efficiency = A_g * (A_c^2 * 1.0 + 2 A_c (1 - A_c) * 0.6) = 0.99 * 0.9595 = 0.949905.
    Ignoring the shared utility gives the falsely optimistic 0.9595.
    """
    assets = [{"id": "GRID", "modes": [_mode("trip", 990, 10)]},
              {"id": "C1", "modes": [_mode("trip", 190, 10)], "requires": ["GRID"]},
              {"id": "C2", "modes": [_mode("trip", 190, 10)], "requires": ["GRID"]}]
    edges = [{"id": "c1", "from": "inlet", "to": "sales", "capacity": 60, "assets": ["C1"]},
             {"id": "c2", "from": "inlet", "to": "sales", "capacity": 60, "assets": ["C2"]}]
    model = {"name": "Independent utility reference case", "example": True, "basis": ONSHORE_SOURCE,
             "source": "inlet", "sink": "sales", "target": 100, "hours": 20000, "volume_unit": "m3",
             "assets": assets, "edges": edges}
    model["provenance"] = _provenance(model, ONSHORE_SOURCE)
    return model


UTILITY_REFERENCE_EXPECTED = 0.99 * (0.95 ** 2 + 2 * 0.95 * 0.05 * 0.6)
UTILITY_REFERENCE_NO_DEPENDENCY = 0.95 ** 2 + 2 * 0.95 * 0.05 * 0.6


def onshore():
    """Synthetic onshore gas plant exercising the 0.3 method features. Invented values only."""
    pump = lambda key: {"id": key, "requires": ["GRID"], "modes": [
        _mode("trip", 1200, 8, exposure="operating", idle_factor=0.1),
        {"id": "start", "distribution": "demand", "probability": 0.02, "loss": 1.0, "logistics": 0.0,
         "mobilisation": 0.0, "repair": 8.0, "repair_distribution": "exponential"}]}
    assets = [{"id": "INLET", "modes": [], "explicit_no_failures": True},
              {"id": "GRID", "modes": [_mode("trip", 3000, 4)]},
              {"id": "COMP-1", "requires": ["GRID"], "modes": [_mode("trip", 1500, 24, exposure="operating")]},
              {"id": "COMP-2", "requires": ["GRID"], "modes": [_mode("trip", 1500, 24, exposure="operating")]},
              {"id": "DEHY", "modes": [_mode("trip", 4000, 12, logistics=2.0)]},
              pump("PUMP-A"), pump("PUMP-B")]
    edges = [{"id": "inlet", "from": "field", "to": "slug", "capacity": 130, "assets": ["INLET"]},
             {"id": "train-1", "from": "slug", "to": "plant", "capacity": 70, "assets": ["COMP-1", "DEHY"],
              "yield": 0.98, "priority": 1},
             {"id": "train-2", "from": "slug", "to": "plant", "capacity": 70, "assets": ["COMP-2", "DEHY"],
              "yield": 0.98, "priority": 2},
             {"id": "rundown", "from": "plant", "to": "tank", "capacity": 140},
             {"id": "pump-A", "from": "tank", "to": "customer", "capacity": 110, "assets": ["PUMP-A"]},
             {"id": "pump-B", "from": "tank", "to": "customer", "capacity": 110, "assets": ["PUMP-B"]}]
    model = {"name": "Synthetic onshore gas plant", "example": True, "basis": ONSHORE_SOURCE,
             "source": "field", "sink": "customer", "target": 100, "feed": 130, "hours": 8760,
             "volume_unit": "m3", "assets": assets, "edges": edges, "crews": 2,
             "buffers": [{"id": "SLUG", "node": "slug", "capacity": 300, "initial": 150, "fill": 30, "draw": 140},
                         {"id": "TANK", "node": "tank", "capacity": 800, "initial": 400, "fill": 40, "draw": 110}],
             "standby_groups": [{"id": "export-pumps", "members": ["PUMP-A", "PUMP-B"], "running": 1}],
             "common_cause": [{"id": "comp-ccf", "assets": ["COMP-1", "COMP-2"], "mtbf": 30000, "loss": 1.0,
                               "logistics": 0.0, "mobilisation": 0.0, "repair": 48.0,
                               "repair_distribution": "exponential"}],
             "closed_access": [[2000, 2072]], "weather_policy": "suspend",
             "maintenance": [{"asset": "COMP-1", "start": 3000, "end": 3048},
                             {"asset": "COMP-2", "start": 3500, "end": 3548}],
             "demand_schedule": [[0, 100], [2160, 90], [6552, 100]],
             "calendar_start": "2027-01-01T00:00",
             "deferral": {"window_h": 168, "recovery_rate": 10},
             "economics": {"currency": "AUD", "cost_basis": "2027 real, synthetic", "source": "EXAMPLE assumption",
                           "value_per_unit": 40.0, "discount_rate_per_year": 0.07}}
    model["provenance"] = _provenance(model, ONSHORE_SOURCE)
    model["provenance"]["standby/export-pumps"] = ONSHORE_SOURCE
    model["provenance"]["ccf/comp-ccf"] = ONSHORE_SOURCE
    return model
