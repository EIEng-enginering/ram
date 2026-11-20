"""Statistical decision support: candidate diffs, paired comparison validity,
option ranking with sampling and input uncertainty, and tornado data.

Kinds of uncertainty are kept separate and labelled:
* ``per_run`` - spread of a metric across replications (P10/P50/P90);
* ``sampling`` - Student-t interval on a mean from finite replications;
* ``paired_delta`` - interval on the mean of matched-replication differences;
* ``input`` - spread of conditional means across sampled input parameters.
"""
from copy import deepcopy

import numpy as np
from scipy.stats import t as student

from .simulation import Simulator
from .study import digest, paired_compare


def model_diff(base, option, path=""):
    """Readable list of changes, shown to the engineer before an option is run or approved."""
    changes = []
    if isinstance(base, dict) and isinstance(option, dict):
        for key in sorted(base.keys() | option.keys()):
            here = f"{path}/{key}" if path else key
            if key not in option:
                changes.append(f"removed {here}")
            elif key not in base:
                changes.append(f"added {here} = {option[key]!r}"[:300])
            else:
                changes.extend(model_diff(base[key], option[key], here))
    elif isinstance(base, list) and isinstance(option, list) and all(isinstance(x, dict) and "id" in x for x in base + option):
        a, b = {x["id"]: x for x in base}, {x["id"]: x for x in option}
        for key in sorted(a.keys() | b.keys()):
            here = f"{path}[{key}]"
            if key not in b:
                changes.append(f"removed {here}")
            elif key not in a:
                changes.append(f"added {here}")
            else:
                changes.extend(model_diff(a[key], b[key], here))
    elif base != option:
        changes.append(f"changed {path}: {base!r} -> {option!r}"[:300])
    return changes


def comparison_validity(base, option):
    """Explain when matched random streams make a paired comparison informative."""
    left, right = Simulator(base), Simulator(option)
    a, b = set(left.modes) | set(left.standby), set(right.modes) | set(right.standby)
    shared = a & b
    notes = []
    fraction = len(shared) / max(1, len(a | b))
    if a != b:
        notes.append(f"{len(a ^ b)} failure processes exist in only one option; their streams are unmatched.")
    changed = [k for k in shared if k in left.modes and k in right.modes and left.modes[k] != right.modes[k]]
    if changed:
        notes.append(f"{len(changed)} shared processes have changed parameters; matched streams still align "
                     "event sequences but correlation is reduced.")
    if [e["id"] for e in base["edges"]] != [e["id"] for e in option["edges"]] or base.get("standby_groups") != option.get("standby_groups"):
        notes.append("Routing or standby logic differs: identical streams can produce different event orders, "
                     "so the variance reduction from pairing is not guaranteed.")
    if left.features != right.features:
        notes.append("The options use different engine features (method profiles differ).")
    return {"matched_stream_fraction": fraction, "notes": notes or ["Same processes and logic; pairing is valid."]}


def compare_options(base, options, seed, n=400):
    """Paired comparison of each option with the base and between adjacent ranked options."""
    results = []
    samples = {}
    base_sim = Simulator(base)
    samples["base"] = np.array([base_sim.replay(seed, i)["efficiency"] for i in range(n)])
    for name, option in options.items():
        sim = Simulator(option)
        samples[name] = np.array([sim.replay(seed, i)["efficiency"] for i in range(n)])
    tq = student.ppf(.975, n - 1)

    def delta(x):
        half = float(tq * np.std(x, ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
        mean = float(np.mean(x))
        return {"kind": "paired_delta", "mean": mean, "ci95": [mean - half, mean + half],
                "significant": bool(half > 0 and abs(mean) > half),
                "p10": float(np.quantile(x, .1)), "p90": float(np.quantile(x, .9))}

    for name, option in options.items():
        d = delta(samples[name] - samples["base"])
        results.append({"option": name, "changes": model_diff(base, option), "difference": d,
                        "validity": comparison_validity(base, option),
                        "interpretation": ("difference resolved at 95%" if d["significant"] else
                                           "no resolved difference: the interval includes zero; do not rank on this run")})
    ranked = sorted(results, key=lambda r: -r["difference"]["mean"])
    adjacent = []
    for a, b in zip(ranked, ranked[1:]):
        d = delta(samples[a["option"]] - samples[b["option"]])
        adjacent.append({"higher": a["option"], "lower": b["option"], "difference": d,
                         "distinguishable": d["significant"]})
    return {"n": n, "seed": seed, "base_hash": digest(base), "ranking": [r["option"] for r in ranked],
            "options": results, "adjacent": adjacent,
            "statement": "Ranking is statistically resolved only where adjacent differences are significant."}


def _apply_bounds(model, assignment):
    sample = deepcopy(model)
    for (asset_id, mode_id, field), value in assignment.items():
        asset = next((a for a in sample["assets"] if a["id"] == asset_id), None)
        mode = next((m for m in asset["modes"] if m["id"] == mode_id), None) if asset else None
        if mode is None or field not in mode:
            raise ValueError(f"{asset_id}/{mode_id}/{field} is not present in every option.")
        mode[field] = value
    return sample


def ranking_under_uncertainty(options, bounds, seed, outer=20, inner=100):
    """Re-rank options for each sampled input set (common samples across options)."""
    if not (2 <= outer <= 500 and 2 <= inner <= 5000):
        raise ValueError("Uncertainty replication counts outside supported bounds.")
    rng = np.random.default_rng(seed)
    names = list(options)
    rankings, means = [], {k: [] for k in names}
    for j in range(outer):
        assignment = {}
        for asset_id, mode_id, field, low, high in bounds:
            if not 0 <= low <= high < np.inf:
                raise ValueError("Invalid uncertainty bounds.")
            assignment[(asset_id, mode_id, field)] = float(rng.uniform(low, high))
        inner_seed = int(np.random.SeedSequence([seed, j, 7]).generate_state(1)[0])
        for name in names:
            sim = Simulator(_apply_bounds(options[name], assignment))
            means[name].append(float(np.mean([sim.replay(inner_seed, i)["efficiency"] for i in range(inner)])))
        rankings.append(tuple(sorted(names, key=lambda k: -means[k][-1])))
    modal = max(set(rankings), key=rankings.count)
    best = {k: sum(1 for r in rankings if r[0] == k) / outer for k in names}
    return {"kind": "input", "outer": outer, "inner": inner, "seed": seed,
            "conditional_mean_percentiles": {k: [float(x) for x in np.quantile(v, [.1, .5, .9])] for k, v in means.items()},
            "probability_best": best, "modal_ranking": list(modal),
            "ranking_changes": 1 - rankings.count(modal) / outer,
            "note": "Each outer sample applies the same input draw to every option; finite inner sampling adds noise."}


def tornado(model, inputs, seed, n=200):
    """inputs: [(label, provenance_key, low_model, high_model)]. Bars sorted by swing."""
    bars = []
    for label, source, low, high in inputs:
        lo, hi = paired_compare(model, low, seed, n), paired_compare(model, high, seed, n)
        bars.append({"input": label, "source": source, "low": lo["difference"]["mean"],
                     "high": hi["difference"]["mean"], "low_ci95": lo["difference"]["ci95"],
                     "high_ci95": hi["difference"]["ci95"],
                     "swing": abs(hi["difference"]["mean"] - lo["difference"]["mean"])})
    return sorted(bars, key=lambda b: -b["swing"])


def render_tornado(bars, path, base_label="efficiency change (percentage points)"):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(8, 0.6 * len(bars) + 1.4), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    labels = [f"{b['input']}\n[{b['source']}]" for b in bars][::-1]
    for i, b in enumerate(bars[::-1]):
        ax.barh(i, 100 * b["low"], color="#b65218", label="low input" if i == 0 else None)
        ax.barh(i, 100 * b["high"], color="#006986", label="high input" if i == 0 else None)
        for value, ci in ((b["low"], b["low_ci95"]), (b["high"], b["high_ci95"])):
            ax.plot([100 * ci[0], 100 * ci[1]], [i, i], color="black", linewidth=1)
    ax.axvline(0, color="#333333", linewidth=.8)
    ax.set_yticks(range(len(bars)), labels, fontsize=8)
    ax.set_xlabel(base_label)
    ax.set_title("Tornado: paired mean change with 95% paired intervals", loc="left", fontsize=10)
    ax.legend(loc="lower right", fontsize=8)
    fig.savefig(path, dpi=130)
