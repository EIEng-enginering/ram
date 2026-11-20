"""Reviewed model revisions, immutable run records and qualified sandbox options."""
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from importlib.resources import files
import json
from threading import Event
from uuid import uuid4

import numpy as np
import scipy

from .simulation import Simulator, simulate, summary

METHOD = "rammodel-des-0.3"
LEGACY_METHOD = "rammodel-des-0.2"
RNG_SCHEME = ("NumPy PCG64; one stream per (asset, mode) from SeedSequence([seed, replication, "
              "8 little-endian uint32 words of SHA-256(repr((asset, mode)))]); exponential repair draws use key "
              "('repair', asset, mode)")


def no_failure_reference(model):
    """Deterministic delivery with every failure process removed (planned outages and schedules kept)."""
    clean = deepcopy(model)
    for asset in clean["assets"]:
        if asset.get("modes") or asset.get("standby_pair"):
            asset["modes"] = []
            asset.pop("standby_pair", None)
            asset["explicit_no_failures"] = True
    clean.pop("common_cause", None)
    return Simulator(clean).replay(0)


def json_text(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return sha256(json_text(value).encode()).hexdigest()


def code_hash():
    root = files("rammodel")
    hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.name.endswith((".py", ".sql"))}
    return digest(hashes)


def now():
    return datetime.now(UTC).isoformat()


def _audit(db, target, action, actor, note):
    db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
               (target, action, actor, now(), note))


def save_model(db, model, actor="desktop user", note="Model saved"):
    """Store the current model and keep every distinct revision readable."""
    fingerprint = digest(model)
    previous = current_model(db)
    db.execute("""INSERT OR IGNORE INTO model_revision VALUES (?,?,?,?,?,?)""",
               (fingerprint, json_text(model), previous[1] if previous else None,
                actor.strip() or "unspecified", note, now()))
    db.execute("""INSERT INTO study VALUES (1,?,?,NULL,NULL)
        ON CONFLICT(id) DO UPDATE SET model_json=excluded.model_json, model_hash=excluded.model_hash,
        reviewer=NULL, reviewed_at=NULL WHERE study.model_hash<>excluded.model_hash""",
               (json_text(model), fingerprint))
    return fingerprint


def current_model(db):
    row = db.execute("SELECT model_json,model_hash,reviewer,reviewed_at FROM study WHERE id=1").fetchone()
    return (json.loads(row[0]), *row[1:]) if row else None


def revisions(db):
    return [dict(zip(("hash", "parent_hash", "actor", "note", "created_at"), r)) for r in db.execute(
        "SELECT hash,parent_hash,actor,note,created_at FROM model_revision ORDER BY created_at, rowid")]


def get_revision(db, fingerprint):
    row = db.execute("SELECT model_json FROM model_revision WHERE hash=?", (fingerprint,)).fetchone()
    if not row:
        raise ValueError("Unknown model revision.")
    return json.loads(row[0])


def library_hash(db):
    """Fingerprint of the stored equipment library, used for stale detection."""
    content = {}
    for table, order in (("source", "id"), ("subsystem", "id"), ("equipment", "id"), ("failure_mode", "id"),
                         ("mode_value", "mode_id, field"), ("mode_value_meta", "mode_id, field"),
                         ("failure_observation", "id")):
        content[table] = [list(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY {order}")]
    return digest(content)


def review_model(db, actor, expected_hash):
    if not actor.strip():
        raise ValueError("A reviewer name is required.")
    row = current_model(db)
    if not row or row[1] != expected_hash:
        raise ValueError("Review the current model revision.")
    model = row[0]
    Simulator(model)
    if review_gaps(model):
        raise ValueError("Resolve review gaps before approving the model: " + "; ".join(review_gaps(model)))
    updated = db.execute("UPDATE study SET reviewer=?,reviewed_at=? WHERE id=1 AND model_hash=?",
                         (actor.strip(), now(), expected_hash))
    if updated.rowcount != 1:
        raise ValueError("The model revision changed.")
    _audit(db, expected_hash, "approve model", actor.strip(), "Reviewed graph and evidence")


def review_gaps(model):
    gaps = list(model.get("unresolved", []))
    if not model.get("basis"):
        gaps.append("Missing study basis")
    provenance = model.get("provenance", {})
    for group in ("assets", "edges"):
        for element in model[group]:
            key = f"{group}/{element['id']}"
            if not provenance.get(key):
                gaps.append(f"Missing source for {key}")
            if group == "assets":
                for parent in element.get("requires", []):
                    key = f"dependencies/{element['id']}/{parent}"
                    if not provenance.get(key):
                        gaps.append(f"Missing source for {key}")
                if element.get("standby_pair") and not provenance.get(f"standby/{element['id']}"):
                    gaps.append(f"Missing standby evidence for {element['id']}")
                for failure in element["modes"]:
                    key = f"modes/{element['id']}/{failure['id']}"
                    if not provenance.get(key):
                        gaps.append(f"Missing source for {key}")
    for field in ("hours", "target", "feed", "buffer", "crews", "closed_access",
                  "spares", "maintenance", "splits"):
        if field in model and not provenance.get(f"study/{field}"):
            gaps.append(f"Missing source for study/{field}")
    return gaps


def calculate(model, *, seed, initial=1000, maximum=100000, progress=None, cancel: Event | None = None):
    sim = Simulator(model)

    def on_progress(n):
        if cancel and cancel.is_set():
            raise InterruptedError("Run cancelled.")
        if progress:
            progress(n)

    result = simulate(sim, seed, initial, maximum, progress=on_progress)
    reference = no_failure_reference(model)
    import platform
    import sys
    from . import __version__
    return {"id": uuid4().hex, "method": METHOD,
            "method_profile": "0.2-compatible (identical event order, streams and LP)" if not sim.features
            else "0.3 features: " + ", ".join(sim.features),
            "model": deepcopy(model), "model_hash": digest(model),
            "code_hash": code_hash(), "code_version": __version__,
            "environment": {"numpy": np.__version__, "scipy": scipy.__version__, "python": sys.version.split()[0],
                            "platform": platform.platform()},
            "rng": RNG_SCHEME,
            "basis": {"initial": initial, "maximum": maximum, "horizon_h": sim.horizon,
                      "target_rate": sim.flow.target, "volume_unit": sim.shipment_unit,
                      "contractual_demand": sim.contract, "no_failure_delivery": reference["delivered"],
                      "statistic": "Lower-tail percentiles and approximate Student-t mean intervals"},
            "created": now(), "result": result}


def save_run(db, record):
    current = current_model(db)
    if not current or digest(record["model"]) != record["model_hash"]:
        raise ValueError("Run has an invalid model snapshot.")
    record.setdefault("library_hash", library_hash(db))
    db.execute("INSERT INTO run VALUES (?,?,?,?)", (record["id"], record["model_hash"],
                                                  json_text(record), record["created"]))


def get_run(db, run_id):
    row = db.execute("SELECT record_json FROM run WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise ValueError("Unknown run.")
    return json.loads(row[0])


def paired_compare(a, b, seed, n=1000, progress=None, cancel=None):
    if type(n) is not int or not 2 <= n <= 100000:
        raise ValueError("Invalid comparison size.")
    left, right = Simulator(a), Simulator(b)
    if (left.horizon, left.flow.target, left.shipment_unit) != (right.horizon, right.flow.target, right.shipment_unit):
        raise ValueError("Comparison requires the same horizon, target and volume units.")
    samples_a, samples_b = np.empty(n), np.empty(n)
    for i in range(n):
        if i % 10 == 0:
            if cancel and cancel.is_set():
                raise InterruptedError("Comparison cancelled.")
            if progress:
                progress(i)
        samples_a[i] = left.replay(seed, i)["efficiency"]
        samples_b[i] = right.replay(seed, i)["efficiency"]
    difference = summary(samples_b - samples_a)
    difference.update(kind="paired_delta", significant=bool(difference["halfwidth"] > 0 and
                                                            abs(difference["mean"]) > difference["halfwidth"]))
    return {"n": n, "seed": seed, "base_hash": digest(a), "alternative_hash": digest(b),
            "base": {**summary(samples_a), "kind": "sampling"}, "alternative": {**summary(samples_b), "kind": "sampling"},
            "difference": difference,
            "note": "P10-P90 are per-run spreads; ci95 is the sampling interval on the mean (paired for difference)."}


def sensitivities(model, options, seed, n=1000):
    output = []
    for name, low, high in options:
        output.append({"input": name, "low": paired_compare(model, low, seed, n),
                       "high": paired_compare(model, high, seed, n)})
    return sorted(output, key=lambda x: abs(x["high"]["difference"]["mean"] -
                                           x["low"]["difference"]["mean"]), reverse=True)


def propagate_uncertainty(model, bounds, seed, outer=30, inner=100):
    """Uniform independent epistemic overrides; summarise conditional means."""
    rng = np.random.default_rng(seed)
    if not (type(outer) is int and 2 <= outer <= 1000 and type(inner) is int and 2 <= inner <= 10000):
        raise ValueError("Uncertainty replication counts outside supported bounds.")
    allowed = {"mtbf", "scale", "median", "shape", "sigma", "logistics", "mobilisation", "repair"}
    estimates = []
    for outer_index in range(outer):
        sample = deepcopy(model)
        for asset_id, mode_id, field, low, high in bounds:
            if field not in allowed or not 0 <= low <= high < np.inf:
                raise ValueError("Invalid uncertainty bounds.")
            asset = next((a for a in sample["assets"] if a["id"] == asset_id), None)
            mode = next((m for m in asset["modes"] if m["id"] == mode_id), None) if asset else None
            if mode is None or field not in mode or not low <= mode[field] <= high:
                raise ValueError("Bounds must bracket an existing parameter.")
            mode[field] = float(rng.uniform(low, high))
        sim = Simulator(sample)
        simulation_seed = int(np.random.SeedSequence([seed, outer_index, 1]).generate_state(1)[0])
        estimates.append(float(np.mean([sim.replay(simulation_seed, i)["efficiency"] for i in range(inner)])))
    return {"outer": outer, "inner": inner, "seed": seed, "sampling": "Independent uniform parameter bounds",
            "conditional_mean_percentiles": [float(x) for x in np.quantile(estimates, [.1, .5, .9])],
            "note": "Finite inner sampling adds noise to the estimated spread."}


def criticality(model, seed, n=200):
    """One-mode removal comparisons. Gains are counterfactual and nonadditive."""
    result = []
    for asset_i, asset in enumerate(model["assets"]):
        for mode_i, mode in enumerate(asset["modes"]):
            option = deepcopy(model)
            other = option["assets"][asset_i]
            del other["modes"][mode_i]
            if not other["modes"]:
                other["explicit_no_failures"] = True
            compared = paired_compare(model, option, seed, n)
            result.append({"equipment": asset["id"], "mode": mode["id"], "gain": compared["difference"]})
    return sorted(result, key=lambda item: item["gain"]["mean"], reverse=True)
