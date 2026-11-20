"""Windows desktop entry and reproducible worked example command."""
from argparse import ArgumentParser
from copy import deepcopy
import json
from pathlib import Path

from .analytics import cold_standby, component, hidden_periodic, independent_group
from .example import (UTILITY_REFERENCE_EXPECTED, UTILITY_REFERENCE_NO_DEPENDENCY, buffer_benchmark,
                      double_buffer, offshore_extended, onshore, separation_options, utility_reference)
from .exchange import export_exchange, import_exchange
from .fixtures import equipment_fixture
from .simulation import Simulator
from .storage import open_case
from .study import calculate, paired_compare, save_model, save_run, sensitivities


def demo(output, runs):
    from .reporting import export
    output.mkdir(parents=True, exist_ok=True)
    case = output / "Synthetic_Offshore.ramcase"
    model = offshore_extended()
    option = double_buffer(model)
    record = calculate(model, seed=42, initial=runs, maximum=runs)
    one, three = separation_options(model)
    analyses = {
        "larger_storage": paired_compare(model, option, 42, runs),
        "single_full_capacity_train": paired_compare(model, one, 42, runs),
        "three_half_capacity_trains": paired_compare(model, three, 42, runs),
        "sensitivity": sensitivities(model, [("storage capacity", model, option)], 42, runs),
        "exact_buffer_cover": Simulator(buffer_benchmark()).replay(42, trace=True),
        "analytics": {"single": component(100, 10), "2oo3": independent_group("kofn", [.9] * 3, 2),
                      "cold_standby": cold_standby(.01, .1), "hidden": hidden_periodic(.0001, 10)}
    }
    record["analysis"] = analyses
    with open_case(case) as db:
        if not db.execute("SELECT 1 FROM source LIMIT 1").fetchone():
            import_exchange(db, equipment_fixture(), "Synthetic fixture", apply=True)
        export_exchange(db, output / "EXAMPLE_Equipment_Library.xlsx")
        export_exchange(db, output / "EXAMPLE_Equipment_CSV")
        save_model(db, model)
        save_run(db, record)
        export(db, record["id"], output / "Reports")
    for path, data in (("Synthetic_Offshore_Model.json", model), ("Run_Comparisons.json", analyses)):
        (output / path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{case} | n={runs} | mean efficiency={record['result']['metrics']['efficiency']['mean']:.6%} "
          f"| converged={record['result']['converged']}")


def utility_reference_check(seed=11, runs=200):
    """Expected (hand calculation in example.utility_reference) versus simulated, with tolerance."""
    sim = Simulator(utility_reference())
    values = [sim.replay(seed, i)["efficiency"] for i in range(runs)]
    mean = sum(values) / runs
    se = (sum((v - mean) ** 2 for v in values) / (runs - 1) / runs) ** 0.5
    tolerance = 4 * se + 0.0015
    return {"case": "Independent utility reference case", "expected": UTILITY_REFERENCE_EXPECTED,
            "expected_derivation": "0.99 * (0.95^2 + 2*0.95*0.05*0.6) = 0.949905",
            "ignoring_shared_utility": UTILITY_REFERENCE_NO_DEPENDENCY, "simulated_mean": mean,
            "standard_error": se, "tolerance": tolerance, "tolerance_rule": "4 SE + 0.0015 start-up bias",
            "seed": seed, "replications": runs, "hours": 20000,
            "pass": abs(mean - UTILITY_REFERENCE_EXPECTED) < tolerance}


def demo_onshore(output, runs):
    from .reporting import export
    output.mkdir(parents=True, exist_ok=True)
    case = output / "Synthetic_Onshore.ramcase"
    model = onshore()
    bigger = deepcopy(model)
    bigger["buffers"][1]["capacity"] *= 2
    bigger["name"] += " – larger product tank"
    record = calculate(model, seed=42, initial=runs, maximum=runs)
    analyses = {"larger_product_tank": paired_compare(model, bigger, 42, runs),
                "utility_reference": utility_reference_check()}
    record["analysis"] = analyses
    with open_case(case) as db:
        save_model(db, model)
        save_run(db, record)
        export(db, record["id"], output / "Reports")
    for path, data in (("Synthetic_Onshore_Model.json", model), ("Onshore_Analyses.json", analyses),
                       ("Utility_Reference_Model.json", utility_reference())):
        (output / path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{case} | n={runs} | mean efficiency={record['result']['metrics']['efficiency']['mean']:.6%} "
          f"| utility reference pass={analyses['utility_reference']['pass']}")


def main():
    parser = ArgumentParser()
    parser.add_argument("--case", type=Path, help="open a RAM case in the desktop")
    parser.add_argument("--demo", type=Path, help="generate the worked example")
    parser.add_argument("--onshore", type=Path, help="generate the onshore 0.3 example and utility reference")
    parser.add_argument("--runs", type=int, default=1000)
    args = parser.parse_args()
    if args.demo:
        demo(args.demo, args.runs)
        return 0
    if args.onshore:
        demo_onshore(args.onshore, args.runs)
        return 0
    from .ui import launch
    return launch(args.case)


if __name__ == "__main__":
    raise SystemExit(main())
