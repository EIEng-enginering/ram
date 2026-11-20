"""Seeded discrete-event production simulation for the supported graph profile.

Method version ``rammodel-des-0.3``. A model that uses none of the 0.3 features
follows exactly the 0.2 event order, random streams and LP calls, so 0.2 runs
replay bit-for-bit (verified by regression tests). 0.3 features:

* operating-exposure failure clocks (aging only while the asset carries flow or,
  for assets without flow edges, while enabled and up), with an optional idle
  aging factor; as-good-as-new or as-bad-as-old restoration;
* fixed or exponential repair durations;
* proof-test downtime for hidden modes;
* common-cause shocks (exponential or deterministic times) affecting several assets;
* explicit standby groups with start-demand failure modes, shared crews and spares;
* weather policy ``continue`` (0.2) or ``suspend`` (active repair pauses while access is closed);
* piecewise-constant demand, feed and edge-capacity schedules;
* calendar month/year reporting by exact interval splitting;
* unmet-demand classification (lost / recovered / potentially deferred) with an
  explicit recovery window and rate; optional economic valuation;
* whole-case and per-buffer volume balance.
"""
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from heapq import heappop, heappush
from math import ceil, exp, inf, log
from typing import Callable

import numpy as np
from scipy.stats import norm, t as student

from .analytics import standby_generator
from .flow import EPS, Flow, number

LEGACY_KEYS = {"buffer", "crews", "spares", "closed_access", "maintenance", "splits"}
NEW_FEATURES = ("buffers", "recycle_edges", "standby_groups", "common_cause", "demand_schedule", "feed_schedule",
                "capacity_schedule", "deferral", "economics", "calendar_start", "weather_policy")


@dataclass(frozen=True)
class Failure:
    asset: str
    mode: str
    distribution: str
    first: float
    second: float | None
    loss: float
    logistics: float
    mobilisation: float
    repair: float
    proof: float | None
    spare: str | None
    exposure: str = "calendar"
    idle_factor: float = 0.0
    restoration: str = "as_good_as_new"
    repair_distribution: str = "fixed"
    test_duration: float = 0.0
    initial_age: float = 0.0
    assets: tuple = ()          # common-cause members
    times: tuple = ()           # deterministic common-cause times

    def lifetime(self, rng):
        if self.distribution == "exponential":
            return rng.exponential(self.first)
        if self.distribution == "weibull":
            return self.first * rng.weibull(self.second)
        return rng.lognormal(np.log(self.first), self.second)

    def residual(self, rng, age):
        """Remaining life given survival to ``age`` (minimal repair / as-bad-as-old)."""
        if self.distribution == "exponential" or age <= 0:
            return self.lifetime(rng)
        u = rng.random()
        if self.distribution == "weibull":
            k, s = self.second, self.first
            return s * ((age / s) ** k - log(1 - u)) ** (1 / k) - age
        # lognormal: sample conditional on T > age by inverse CDF
        f_age = norm.cdf((log(age) - log(self.first)) / self.second)
        p = f_age + u * (1 - f_age)
        return max(0.0, self.first * exp(self.second * norm.ppf(min(p, 1 - 1e-16))) - age)

    @property
    def demand(self):
        return self.distribution == "demand"


def _failure(asset, data):
    distribution = data["distribution"]
    exposure = data.get("exposure", "calendar")
    if exposure not in ("calendar", "operating"):
        raise ValueError("Failure exposure basis must be calendar or operating.")
    if distribution == "demand":
        p = number(data["probability"], "start-demand failure probability")
        if p > 1:
            raise ValueError("Demand failure probability must be in [0, 1].")
        first, second = p, None
    else:
        key = {"exponential": "mtbf", "weibull": "scale", "lognormal": "median"}.get(distribution)
        if key is None:
            raise ValueError("This simulation profile requires a supported distribution.")
        shape = {"weibull": "shape", "lognormal": "sigma"}.get(distribution)
        first = number(data[key], key, EPS)
        second = number(data[shape], shape, EPS) if shape else None
    loss = number(data["loss"], "failure capacity loss")
    if loss > 1:
        raise ValueError("Failure capacity loss must be in [0, 1].")
    proof = data.get("proof")
    if data.get("detection") not in (None, "hidden" if proof is not None else "revealed"):
        raise ValueError("Failure detection basis and proof-test interval disagree.")
    restoration = data.get("restoration", "as_good_as_new")
    repair_distribution = data.get("repair_distribution", "fixed")
    if restoration not in ("as_good_as_new", "as_bad_as_old"):
        raise ValueError("Restoration must be as_good_as_new or as_bad_as_old.")
    if repair_distribution not in ("fixed", "exponential"):
        raise ValueError("Repair distribution must be fixed or exponential.")
    idle = number(data.get("idle_factor", 0.0), "idle aging factor")
    if idle > 1 or (idle and exposure != "operating"):
        raise ValueError("Idle aging factor in [0, 1] applies only to operating exposure.")
    test = number(data.get("test_duration", 0.0), "proof-test duration")
    if test and proof is None:
        raise ValueError("Proof-test duration requires a proof-test interval.")
    if test and test >= proof:
        raise ValueError("Proof-test duration must be shorter than the interval.")
    return Failure(asset, data["id"], distribution, first, second, loss,
                   *(number(data[k], k) for k in ("logistics", "mobilisation", "repair")),
                   number(proof, "proof interval", EPS) if proof is not None else None,
                   data.get("spare"), exposure, idle, restoration, repair_distribution, test,
                   number(data.get("initial_age", 0.0), "initial age"))


def _schedule(raw, name, minimum=0.0):
    points = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"{name} entries are [hour, rate].")
        points.append((number(item[0], f"{name} hour"), number(item[1], f"{name} rate", minimum)))
    if [p[0] for p in points] != sorted({p[0] for p in points}):
        raise ValueError(f"{name} hours must be strictly increasing.")
    return tuple(points)


def _rate_at(points, base, hour):
    value = base
    for when, rate in points:
        if when <= hour:
            value = rate
    return value


class Simulator:
    def __init__(self, model):
        try:
            self._build(model)
        except KeyError as error:
            raise ValueError(f"Incomplete model input: missing {error.args[0]!r}.") from error

    def _build(self, model):
        self.model = model
        unknown_features = {"products", "standby", "priorities"} & model.keys()
        if unknown_features:
            raise ValueError(f"Unsupported model features: {', '.join(sorted(unknown_features))}")
        if "recycles" in model:
            raise ValueError("Unsupported model features: recycles (declare recycle_edges with explicit capacities)")
        self.features = sorted(k for k in NEW_FEATURES if k in model)
        edge_keys = {k for e in model["edges"] for k in e} & {"priority", "yield"}
        mode_keys = {k for a in model["assets"] for m in a["modes"] for k in m} & {
            "exposure", "restoration", "repair_distribution", "test_duration", "idle_factor", "initial_age"}
        if any(m.get("distribution") == "demand" for a in model["assets"] for m in a["modes"]):
            mode_keys.add("demand")
        self.features += sorted(f"edge:{k}" for k in edge_keys) + sorted(f"mode:{k}" for k in mode_keys)
        self.flow = Flow(model)
        self.horizon = number(model["hours"], "study hours", EPS)
        self.assets = {a["id"]: a for a in model["assets"]}
        if len(self.assets) != len(model["assets"]):
            raise ValueError("Duplicate asset ID.")
        self.modes, self.standby = {}, {}
        for asset, data in self.assets.items():
            if config := data.get("standby_pair"):
                if data["modes"]:
                    raise ValueError(f"{asset}: standby and ordinary modes cannot be combined on one asset.")
                active_rate = 1 / number(config["active_mtbf"], "active MTBF", EPS)
                idle = config.get("idle_mtbf")
                idle_rate = 1 / number(idle, "standby MTBF", EPS) if idle is not None else 0
                rate = 1 / number(config["repair_mean"], "standby mean repair", EPS)
                switch = number(config["switch_failure"], "switch failure")
                self.standby[asset] = standby_generator(active_rate, idle_rate, rate, switch)
            if not data["modes"] and asset not in self.standby and data.get("explicit_no_failures") is not True:
                raise ValueError(f"{asset}: missing failure data. Enter a failure model or explicitly specify no failures.")
            for raw in data["modes"]:
                failure = _failure(asset, raw)
                key = (asset, failure.mode)
                if key in self.modes:
                    raise ValueError(f"Duplicate failure mode {key}.")
                if failure.demand and failure.logistics + failure.mobilisation + failure.repair <= 0:
                    raise ValueError(f"{key}: a start-demand failure needs a positive restoration time.")
                if failure.demand and asset not in {m for g in model.get("standby_groups", []) for m in g["members"]}:
                    raise ValueError(f"{key}: start-demand modes apply only to standby group members.")
                self.modes[key] = failure
        self.ccf = {}
        for raw in model.get("common_cause", []):
            members = tuple(raw["assets"])
            if len(members) < 2 or len(set(members)) != len(members) or not set(members) <= self.assets.keys():
                raise ValueError(f"Common-cause group {raw.get('id')} needs two or more distinct known assets.")
            times = tuple(sorted(number(x, "common-cause time") for x in raw.get("times", [])))
            if bool(times) == (raw.get("mtbf") is not None):
                raise ValueError("Give exactly one of a common-cause MTBF or deterministic times.")
            data = {**raw, "distribution": "exponential", "mtbf": raw.get("mtbf", 1.0)}
            failure = _failure("@ccf", data)
            failure = Failure(**{**failure.__dict__, "assets": members, "times": times,
                                 "distribution": "exponential" if not times else "times"})
            key = ("@ccf", raw["id"])
            if key in self.ccf:
                raise ValueError("Duplicate common-cause ID.")
            self.ccf[key] = failure
            self.modes[key] = failure
        self.dependencies = {a: tuple(d.get("requires", [])) for a, d in self.assets.items()}
        self.thresholds = {}
        for asset, dependencies in self.dependencies.items():
            threshold = self.assets[asset].get("requires_k", len(dependencies))
            if len(dependencies) != len(set(dependencies)) or type(threshold) is not int or not 0 <= threshold <= len(dependencies):
                raise ValueError(f"Invalid dependency voting rule for {asset}.")
            self.thresholds[asset] = threshold
        known = set(self.assets)
        for e in self.flow.edges:
            if not set(e.get("assets", [])) <= known:
                raise ValueError(f"Unknown asset on flow edge {e['id']}.")
        for a, dependencies in self.dependencies.items():
            if not set(dependencies) <= known or a in dependencies:
                raise ValueError(f"Invalid dependencies for {a}.")
        self.order = []
        remaining = set(known)
        while remaining:
            ready = sorted(a for a in remaining if not (set(self.dependencies[a]) & remaining))
            if not ready:
                raise ValueError("Asset dependencies contain a cycle.")
            self.order.extend(ready)
            remaining.difference_update(ready)
        self.crews = model.get("crews")
        if self.crews is not None and (type(self.crews) is not int or self.crews < 1):
            raise ValueError("Crew count must be a positive integer.")
        self.spares = model.get("spares", {})
        for name, config in self.spares.items():
            if type(config["initial"]) is not int or config["initial"] < 0:
                raise ValueError(f"Invalid spare stock for {name}.")
            number(config["lead"], "spare replenishment lead", EPS)
        if any(m.spare is not None and m.spare not in self.spares for m in self.modes.values()):
            raise ValueError("Unknown spares pool.")
        self.weather = tuple(sorted((number(a, "weather start"), number(b, "weather end"))
                                    for a, b in model.get("closed_access", [])))
        if any(a >= b for a, b in self.weather):
            raise ValueError("Invalid access window.")
        self.weather_policy = model.get("weather_policy", "continue")
        if self.weather_policy not in ("continue", "suspend"):
            raise ValueError("Weather policy must be continue or suspend.")
        self.maintenance = []
        for m in model.get("maintenance", []):
            a = m["asset"]
            start, end = number(m["start"], "maintenance start"), number(m["end"], "maintenance end")
            if a not in known or not start < end:
                raise ValueError("Invalid maintenance window.")
            self.maintenance.append((a, start, end))
        self.shipment_unit = model.get("volume_unit", "volume units")
        # Standby groups: running set chosen deterministically in member order.
        self.groups = []
        grouped = set()
        for g in model.get("standby_groups", []):
            members = tuple(g["members"])
            running = g.get("running", 1)
            if (len(members) < 2 or not set(members) <= known or set(members) & grouped or
                    type(running) is not int or not 1 <= running < len(members)):
                raise ValueError(f"Invalid standby group {g.get('id')}.")
            if any(a in self.standby for a in members):
                raise ValueError("A standby_pair asset cannot also be a standby group member.")
            grouped.update(members)
            self.groups.append((g["id"], members, running))
        self.grouped = grouped
        self.edges_of = {a: [i for i, e in enumerate(self.flow.edges) if a in e.get("assets", [])] for a in known}
        # Schedules and calendar.
        self.demand = _schedule(model.get("demand_schedule", []), "demand schedule")
        self.feed_points = _schedule(model.get("feed_schedule", []), "feed schedule")
        self.capacity_plan = []
        for c in model.get("capacity_schedule", []):
            if c["edge"] not in self.flow.ids:
                raise ValueError("Unknown edge in capacity schedule.")
            start, end = number(c["start"], "capacity change start"), number(c["end"], "capacity change end")
            if not start < end:
                raise ValueError("Invalid capacity change window.")
            self.capacity_plan.append((self.flow.ids.index(c["edge"]), start, end, number(c["capacity"], "capacity")))
        cuts = sorted({0.0, self.horizon, *(p[0] for p in self.demand if p[0] < self.horizon)})
        self.contract = (self.flow.target * self.horizon if not self.demand else
                         sum((b - a) * _rate_at(self.demand, self.flow.target, a) for a, b in zip(cuts, cuts[1:])))
        if self.contract <= 0:
            raise ValueError("Contractual demand over the horizon is zero; efficiency is undefined.")
        self.periods = []
        if start := model.get("calendar_start"):
            origin = datetime.fromisoformat(start)
            edges, t = [], origin
            while True:
                t = (t.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                hour = (t - origin).total_seconds() / 3600
                if hour >= self.horizon:
                    break
                edges.append(hour)
            self.calendar_origin = origin
            self.period_edges = edges
            labels, t = [], origin
            for _ in range(len(edges) + 1):
                labels.append(t.strftime("%Y-%m"))
                t = (t.replace(day=1) + timedelta(days=32)).replace(day=1)
            self.period_labels = labels
        else:
            self.period_edges, self.period_labels = [], []
        self.deferral = None
        if (d := model.get("deferral")) is not None:
            self.deferral = (number(d["window_h"], "recovery window", EPS), number(d["recovery_rate"], "recovery rate", EPS))
        self.economics = None
        if (e := model.get("economics")) is not None:
            if not all(isinstance(e.get(k), str) and e[k].strip() for k in ("currency", "cost_basis", "source")):
                raise ValueError("Economic valuation needs currency, cost_basis and source text.")
            self.economics = {"currency": e["currency"], "cost_basis": e["cost_basis"], "source": e["source"],
                              "value_per_unit": number(e["value_per_unit"], "value per unit"),
                              "discount_rate": number(e.get("discount_rate_per_year", 0.0), "discount rate"),
                              "timing": "continuous discounting at the time volume is classified lost"}

    def replay(self, seed, replication=0, trace=False):
        if type(seed) is not int or seed < 0 or type(replication) is not int or replication < 0:
            raise ValueError("Seed and replication must be nonnegative integers.")
        return _Life(self, seed, replication, trace).run()


def _stream(seed, replication, key):
    digest = sha256(repr(key).encode()).digest()
    entropy = [seed, replication] + [int.from_bytes(digest[i:i+4], "little") for i in range(0, 32, 4)]
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))


class _Life:
    def __init__(self, sim, seed, replication, trace):
        self.sim, self.trace = sim, trace
        self.seed, self.replication = seed, replication
        self.time = 0.0
        self.sequence = 0
        self.queue = []
        self.failed, self.ready = set(), []
        self.active = 0
        self.crew_hours = self.delivered = 0.0
        self.stock = {name: x["initial"] for name, x in sim.spares.items()}
        self.maintenance = Counter()
        self.testing = Counter()
        self.counts, self.down, self.asset_down, self.loss = Counter(), Counter(), Counter(), Counter()
        self.levels = [b.initial for b in sim.flow.buffers]
        self.level = self.levels[0] if sim.flow.buffer else 0.0
        self.intervals, self.events = [], []
        self.random, self.repair_random = {}, {}
        self.standby = dict.fromkeys(sim.standby, 0)
        self.clock = {}        # operating-exposure modes: [remaining, rate, last, token]
        self.age = {}          # accumulated exposure for as-bad-as-old modes
        self.tokens = Counter()
        self.jobs = {}         # suspend policy: key -> [remaining, start, token]
        self.target = sim.flow.target
        self.feed = sim.flow.feed
        self.cap_override = {}
        self.running = {g: list(members[:k]) for g, members, k in sim.groups}
        self.backlog = []      # [volume, created hour]
        self.lost = self.recovered = 0.0
        self.lost_value = 0.0
        self.balance = Counter()
        self.periods = {}
        for key in sorted(set(sim.modes) | {(asset, "standby_pair") for asset in self.standby}):
            asset, mode = key
            self.random[key] = _stream(seed, replication, key)
            if key in sim.modes:
                m = sim.modes[key]
                if m.demand or m.times:
                    continue
                if m.exposure == "operating":
                    self.age[key] = m.initial_age
                    life = self.draw_life(key)
                    self.clock[key] = [life, None, 0.0, 0, life]
                else:
                    self.schedule_failure(key)
            else:
                self.schedule_standby(key[0])
        for asset, start, end in sim.maintenance:
            self.add(start, "maintenance_start", asset)
            self.add(end, "maintenance_end", asset)
        for _, end in sim.weather:
            self.add(end, "access_open", None)
        # 0.3 events are queued after all 0.2 events so legacy sequence numbers are unchanged.
        if sim.weather_policy == "suspend":
            for start, _ in sim.weather:
                self.add(start, "access_close", None)
        for key, m in sorted(sim.modes.items()):
            if m.test_duration:
                k = 1
                while k * m.proof < sim.horizon:
                    self.add(k * m.proof, "test_start", m.asset)
                    self.add(k * m.proof + m.test_duration, "test_end", m.asset)
                    k += 1
            if m.times:
                for when in m.times:
                    self.add(when, "fail_at", key)
        for when, rate in sim.demand:
            self.add(when, "demand_change", rate)
        for when, rate in sim.feed_points:
            self.add(when, "feed_change", rate)
        for i, (edge, start, end, capacity) in enumerate(sim.capacity_plan):
            self.add(start, "capacity_start", i)
            self.add(end, "capacity_end", i)
        if sim.demand and sim.demand[0][0] == 0:
            self.target = sim.demand[0][1]
        if sim.feed_points and sim.feed_points[0][0] == 0:
            self.feed = sim.feed_points[0][1]

    # ---------------------------------------------------------------- scheduling
    def add(self, when, action, key):
        if when < self.sim.horizon:
            self.sequence += 1
            heappush(self.queue, (when, self.sequence, action, key))

    def draw_life(self, key):
        m = self.sim.modes[key]
        if m.restoration == "as_bad_as_old":
            return m.residual(self.random[key], self.age.get(key, m.initial_age))
        return m.lifetime(self.random[key])

    def schedule_failure(self, key):
        m = self.sim.modes[key]
        if m.exposure == "operating":
            life = self.draw_life(key)
            self.clock[key] = [life, None, self.time, self.tokens[key], life]
            return
        if m.restoration == "as_bad_as_old":
            self.age.setdefault(key, m.initial_age)
            duration = self.draw_life(key)
            self.add(max(self.time + EPS, self.time + duration), "fail_age", (key, duration))
            return
        duration = m.lifetime(self.random[key])
        self.add(max(self.time + EPS, self.time + duration), "fail", key)

    def schedule_standby(self, asset):
        state = self.standby[asset]
        row = self.sim.standby[asset][state]
        rate = -row[state]
        if rate > 0:
            rng = self.random[(asset, "standby_pair")]
            delay = rng.exponential(1 / rate)
            weights = [x / rate if x > 0 else 0 for x in row]
            target = int(rng.choice(len(row), p=weights))
            self.add(max(self.time + EPS, self.time + delay), "standby_transition", (asset, target))

    def record(self, action, key):
        if self.trace:
            self.events.append({"hour": self.time, "event": action, "item": key})

    def fail(self, key):
        m = self.sim.modes[key]
        self.failed.add(key)
        self.counts[key] += 1
        detected = ceil(self.time / m.proof) * m.proof if m.proof else self.time
        self.add(detected, "detected", key)

    def stale(self, action, key):
        if action == "fail_op":
            key, token = key
            return token != self.tokens[key] or key in self.failed
        if action == "restore_job":
            key, token = key
            return key not in self.jobs or self.jobs[key][2] != token
        return False

    def event(self, action, key):
        if self.stale(action, key):
            return      # superseded clock or paused repair: no effect and not traced
        self.record(action, key)
        if action == "standby_transition":
            asset, target = key
            if self.standby[asset] < 2 <= target:
                self.counts[(asset, "standby_pair")] += 1
            self.standby[asset] = target
            self.schedule_standby(asset)
        elif action == "fail":
            self.fail(key)
        elif action == "fail_age":
            key, duration = key
            self.age[key] = self.age.get(key, 0.0) + duration
            self.fail(key)
        elif action == "fail_op":
            key, token = key
            if token == self.tokens[key] and key not in self.failed:
                drawn = self.clock.pop(key)[4]
                self.age[key] = self.age.get(key, 0.0) + drawn
                self.fail(key)
        elif action == "fail_at":
            if key not in self.failed:
                self.fail(key)
        elif action == "detected":
            m = self.sim.modes[key]
            self.add(self.time + m.logistics + m.mobilisation, "ready", key)
        elif action == "ready":
            self.ready.append(key)
        elif action == "restore":
            self.restored(key)
        elif action == "restore_job":
            key, token = key
            if key in self.jobs and self.jobs[key][2] == token:
                del self.jobs[key]
                self.restored(key)
        elif action == "access_close":
            for key, job in self.jobs.items():
                if job[1] is not None:
                    job[0] -= self.time - job[1]
                    job[1] = None
                    job[2] += 1
        elif action == "access_open" and self.sim.weather_policy == "suspend":
            if not any(a <= self.time < b for a, b in self.sim.weather):
                for key, job in sorted(self.jobs.items()):
                    if job[1] is None:
                        job[1] = self.time
                        self.add(self.time + max(job[0], 0.0), "restore_job", (key, job[2]))
        elif action == "replenish":
            self.stock[key] += 1
        elif action == "maintenance_start":
            self.maintenance[key] += 1
        elif action == "maintenance_end":
            self.maintenance[key] -= 1
        elif action == "test_start":
            self.testing[key] += 1
        elif action == "test_end":
            self.testing[key] -= 1
        elif action == "demand_change":
            self.target = key
        elif action == "feed_change":
            self.feed = key
        elif action == "capacity_start":
            edge, _, _, capacity = self.sim.capacity_plan[key]
            self.cap_override[edge] = capacity
        elif action == "capacity_end":
            edge = self.sim.capacity_plan[key][0]
            self.cap_override.pop(edge, None)

    def restored(self, key):
        self.failed.remove(key)
        self.active -= 1
        m = self.sim.modes[key]
        if m.demand or m.times:
            return
        if m.exposure == "operating":
            self.tokens[key] += 1
        self.schedule_failure(key)

    def repair_time(self, key):
        m = self.sim.modes[key]
        if m.repair_distribution == "fixed":
            return m.repair
        if key not in self.repair_random:
            self.repair_random[key] = _stream(self.seed, self.replication, ("repair",) + key)
        return self.repair_random[key].exponential(m.repair) if m.repair > 0 else 0.0

    def start_repairs(self):
        if not self.ready or any(a <= self.time < b for a, b in self.sim.weather):
            return
        blocked = []
        for key in self.ready:
            m = self.sim.modes[key]
            if (self.sim.crews is not None and self.active >= self.sim.crews) or (
                m.spare is not None and self.stock[m.spare] <= 0
            ):
                blocked.append(key)
                continue
            if m.spare is not None:
                self.stock[m.spare] -= 1
                self.add(self.time + self.sim.spares[m.spare]["lead"], "replenish", m.spare)
            self.active += 1
            self.record("repair_start", key)
            duration = self.repair_time(key)
            if self.sim.weather_policy == "suspend":
                token = self.jobs[key][2] + 1 if key in self.jobs else 0
                self.jobs[key] = [duration, self.time, token]
                self.add(self.time + duration, "restore_job", (key, token))
            else:
                self.add(self.time + duration, "restore", key)
        self.ready = blocked

    # ---------------------------------------------------------------- state
    def raw_down(self):
        down = {a: float(self.maintenance[a] > 0 or self.testing[a] > 0) for a in self.sim.assets}
        for key in self.failed:
            m = self.sim.modes[key]
            for a in (m.assets or (key[0],)):
                down[a] = max(down[a], m.loss)
        for a, state in self.standby.items():
            if state >= 2:
                down[a] = 1.0
        return down

    def enabled(self, down):
        factors = {}
        for a in self.sim.order:
            ok = sum(factors[parent] > EPS for parent in self.sim.dependencies[a]) >= self.sim.thresholds[a]
            factors[a] = 1 - down[a] if ok else 0.0
        return factors

    def select_running(self):
        """Keep running members; start idle members in listed order. Returns True if a start failed."""
        if not self.sim.groups:
            return False
        changed = False
        factors = self.enabled(self.raw_down())
        for group, members, k in self.sim.groups:
            keep = [m for m in self.running[group] if factors[m] > EPS][:k]
            for m in members:
                if len(keep) >= k:
                    break
                if m in keep or factors[m] <= EPS:
                    continue
                failed_start = False
                if self.time > 0:
                    for key in sorted(x for x in self.sim.modes if x[0] == m and self.sim.modes[x].demand):
                        if key in self.failed:
                            continue
                        if self.random[key].random() < self.sim.modes[key].first:
                            self.record("start_failure", key)
                            self.fail(key)
                            failed_start = changed = True
                            break
                if not failed_start:
                    keep.append(m)
                    self.record("start", m)
            self.running[group] = keep
        return changed

    def factors(self):
        factors = self.enabled(self.raw_down())
        if self.sim.groups:
            running = {m for members in self.running.values() for m in members}
            for a in self.sim.grouped:
                if a not in running:
                    factors[a] = 0.0
        return factors

    def update_clocks(self, factors, flow):
        if not self.clock:
            return
        down = self.raw_down()
        for key, clock in self.clock.items():
            m = self.sim.modes[key]
            a = m.asset
            edges = self.sim.edges_of[a]
            operating = factors[a] > EPS and (not edges or any(flow[i] > EPS for i in edges))
            # Idle aging applies only to an available, non-operating unit. A unit that is failed
            # (another mode), under maintenance or under test does not age.
            rate = 1.0 if operating else (0.0 if down[a] > EPS else m.idle_factor)
            remaining, old, last, token, drawn = clock
            if old is not None:
                remaining -= (self.time - last) * old
            if old == rate:
                clock[0], clock[2] = remaining, self.time
                continue
            self.tokens[key] += 1
            token = self.tokens[key]
            self.clock[key] = clock = [max(remaining, 0.0), rate, self.time, token, drawn]
            if rate > 0:
                self.add(max(self.time + EPS, self.time + clock[0] / rate), "fail_op", (key, token))

    def account(self, start, end, delivered, catchup, demand, shortfall):
        """Split one constant-rate interval exactly across calendar months."""
        if not self.sim.period_labels:
            return
        edges, labels = self.sim.period_edges, self.sim.period_labels
        t = start
        while t < end:
            i = bisect_right(edges, t)
            stop = min(end, edges[i] if i < len(edges) else end)
            dt = stop - t
            p = self.periods.setdefault(labels[i], Counter())
            p["hours"] += dt
            p["demand"] += dt * demand
            p["delivered"] += dt * (delivered + catchup)
            p["shortfall"] += dt * shortfall
            p["recovered"] += dt * catchup
            t = stop

    def classify_lost(self, volume, when, until=None):
        """Lost at instant ``when`` or uniformly over [when, until] (exact continuous discounting)."""
        self.lost += volume
        if self.sim.economics:
            e = self.sim.economics
            k = log(1 + e["discount_rate"]) / 8760
            if until is None or until <= when or k == 0:
                factor = exp(-k * when)
            else:
                factor = (exp(-k * when) - exp(-k * until)) / (k * (until - when))
            self.lost_value += volume * e["value_per_unit"] * factor
        if self.sim.period_labels:
            label = self.sim.period_labels[bisect_right(self.sim.period_edges, min(when, self.sim.horizon - EPS))]
            self.periods.setdefault(label, Counter())["lost"] += volume

    # ---------------------------------------------------------------- main loop
    def run(self):
        sim = self.sim
        horizon = sim.horizon
        flow = sim.flow
        legacy = not sim.features
        multi = len(flow.buffers) > 1 or not legacy
        window = sim.deferral
        while self.time < horizon:
            while True:
                while self.queue and self.queue[0][0] <= self.time:
                    _, _, action, key = heappop(self.queue)
                    self.event(action, key)
                self.start_repairs()
                if self.select_running():
                    continue
                if not self.queue or self.queue[0][0] > self.time:
                    break
            availability = self.factors()
            caps = [
                (self.cap_override.get(i, nominal)) * min((availability[a] for a in e.get("assets", [])), default=1.0)
                for i, (e, nominal) in enumerate(zip(flow.edges, flow.capacity, strict=True))
            ]
            target = self.target
            backlog = sum(v for v, _ in self.backlog)
            if multi:
                state = flow.solve_state(caps, tuple(self.levels), target, self.feed,
                                         window[1] if window and backlog > EPS else 0.0)
                delivered, net, edge_flow, nets = state.delivered, state.net, state.flow, state.nets
            else:
                delivered, net, edge_flow = flow.solve(caps, self.level, target)
                nets = (net,)
                state = None
            self.update_clocks(availability, edge_flow)
            end = min(horizon, self.queue[0][0] if self.queue else inf,
                      self.time + (flow.next_boundary(tuple(self.levels), nets) if multi
                                   else flow.next_boundary(self.level, net)))
            catchup = state.catchup if state else 0.0
            if catchup > EPS:
                end = min(end, self.time + backlog / catchup)
            if window and self.backlog:
                end = min(end, self.backlog[0][1] + window[0])
            duration = end - self.time
            if duration <= 0:
                if window and self.backlog and self.backlog[0][1] + window[0] <= self.time:
                    volume, created = self.backlog.pop(0)
                    self.classify_lost(volume, self.time)
                    continue
                raise RuntimeError("Flow event scheduler did not advance.")
            inventory = self.level
            if multi:
                starts = list(self.levels)
                for i, b in enumerate(flow.buffers):
                    self.levels[i] = min(b.capacity, max(0.0, self.levels[i] + duration * nets[i]))
                    self.balance[f"buffer:{b.id}:in"] += duration * max(nets[i], 0.0)
                    self.balance[f"buffer:{b.id}:out"] += duration * max(-nets[i], 0.0)
                self.level = self.levels[0] if flow.buffer else 0.0
                self.balance["supply"] += duration * state.supply
                self.balance["yield_loss"] += duration * state.losses
            elif flow.buffer:
                self.level = min(flow.buffer.capacity, max(0.0, inventory + duration * net))
                self.levels[0] = self.level
            self.delivered += duration * (delivered + catchup)
            self.crew_hours += duration * self.active
            for key in self.failed:
                self.down[key] += duration
            for asset, state_ in self.standby.items():
                if state_ >= 2:
                    self.down[(asset, "standby_pair")] += duration
            for asset, factor in availability.items():
                if factor <= EPS and not (asset in sim.grouped and self.member_idle_available(asset)):
                    self.asset_down[asset] += duration
            loss = duration * max(0.0, target - delivered)
            causes = sorted(f"{a}/{m}" for a, m in self.failed if sim.modes[(a, m)].loss)
            causes.extend(sorted(f"{a}/standby_pair" for a, s in self.standby.items() if s >= 2))
            causes.extend(sorted(f"{a}/planned" for a, n in self.maintenance.items() if n > 0))
            causes.extend(sorted(f"{a}/proof test" for a, n in self.testing.items() if n > 0))
            if loss > EPS:
                self.loss[" + ".join(causes) if causes else "No active outage (capacity or inventory)"] += loss
            if window:
                if catchup > EPS:
                    paid = duration * catchup
                    self.recovered += paid
                    while paid > EPS and self.backlog:
                        take = min(paid, self.backlog[0][0])
                        self.backlog[0][0] -= take
                        paid -= take
                        if self.backlog[0][0] <= EPS:
                            self.backlog.pop(0)
                if loss > EPS:
                    self.backlog.append([loss, self.time])
            elif loss > EPS and not legacy:
                self.classify_lost(loss, self.time, end)
            self.account(self.time, end, delivered, catchup, target, max(0.0, target - delivered))
            if self.trace:
                self.intervals.append({"start": self.time, "end": end, "delivery": delivered + catchup, "target": target,
                                       "buffer_start": inventory, "buffer_end": self.level,
                                       "edge_flow": dict(zip(flow.ids, edge_flow, strict=True)), "loss": loss,
                                       "causes": causes, **({"buffer_levels_end": dict(zip(
                                           [b.id for b in flow.buffers], self.levels))} if multi else {})})
            self.time = end
            if window:
                while self.backlog and self.backlog[0][1] + window[0] <= self.time + EPS:
                    volume, created = self.backlog.pop(0)
                    self.classify_lost(volume, created + window[0])
        tracked_modes = sim.modes.keys() | {(a, "standby_pair") for a in self.standby}
        name = lambda a, m: f"CCF:{m}" if a == "@ccf" else f"{a}/{m}"
        result = {
            "efficiency": self.delivered / (sim.flow.target * horizon) if not sim.demand else self.delivered / sim.contract,
            "delivered": self.delivered,
            "shortfall": max(0.0, sim.contract - self.delivered + self.recovered),
            "crew_utilisation": self.crew_hours / (horizon * sim.crews) if sim.crews else None,
            "asset_availability": {a: 1 - self.asset_down[a] / horizon for a in sim.assets},
            "mode_downtime": {name(a, m): self.down[(a, m)] for a, m in sorted(tracked_modes)},
            "failures": {name(a, m): self.counts[(a, m)] for a, m in sorted(tracked_modes)},
            "loss_groups": dict(self.loss), "buffer_end": self.level if not multi else sum(self.levels),
            "intervals": self.intervals, "events": self.events,
        }
        if not legacy:
            deferred = sum(v for v, _ in self.backlog)
            result.update({"contract": sim.contract, "lost": self.lost, "recovered": self.recovered,
                           "deferred": deferred, "buffer_levels": {b.id: x for b, x in zip(flow.buffers, self.levels)},
                           "policy": "recoverable within window" if window else "none: unmet demand is lost"})
            initial = sum(b.initial for b in flow.buffers)
            self.balance["delivered"] = self.delivered
            self.balance["inventory_change"] = sum(self.levels) - initial
            self.balance["residual"] = (self.balance["supply"] - self.delivered - self.balance["inventory_change"]
                                        - self.balance["yield_loss"])
            result["balance"] = dict(self.balance)
            if sim.economics:
                result["lost_value"] = self.lost_value
            if sim.period_labels:
                result["periods"] = {k: dict(v) for k, v in sorted(self.periods.items())}
                years = {}
                for label, data in result["periods"].items():
                    years.setdefault(label[:4], Counter()).update(data)
                result["years"] = {k: dict(v) for k, v in sorted(years.items())}
        return result

    def member_idle_available(self, asset):
        down = self.raw_down()
        return down[asset] < 1 - EPS and asset not in {m for ms in self.running.values() for m in ms}


def summary(values):
    n = len(values)
    mean = float(np.mean(values))
    half = float(student.ppf(.975, n - 1) * np.std(values, ddof=1) / np.sqrt(n))
    return {"mean": mean, "p10": float(np.quantile(values, .1)), "p50": float(np.quantile(values, .5)),
            "p90": float(np.quantile(values, .9)), "ci95": [mean - half, mean + half], "halfwidth": half}


def diagnostics(values, shortfalls, n_events, stochastic):
    """Evidence on the sampling basis; never certifies zero risk."""
    n = len(values)
    with_loss = int(sum(1 for s in shortfalls if s > EPS))
    out = {"replications": n, "replications_with_shortfall": with_loss,
           "replications_with_failure_events": int(sum(1 for e in n_events if e > 0)),
           "zero_sample_variance": bool(np.std(values) == 0)}
    if with_loss == 0:
        out["note"] = ("No shortfall observed in any replication. This is not evidence of zero risk; "
                       f"the one-sided 95% upper bound on the per-replication shortfall probability is {3 / n:.3g} (rule of three).")
        out["shortfall_probability_upper_95"] = 3 / n
    elif with_loss < 10:
        out["note"] = (f"Rare-event regime: only {with_loss} replications show shortfall; Student-t intervals on "
                       "the mean are unreliable. Increase replications or use a variance-reduction method.")
        out["rare_event"] = True
    mean_short = float(np.mean(shortfalls))
    if mean_short > 0 and n > 1:
        half = float(student.ppf(.975, n - 1) * np.std(shortfalls, ddof=1) / np.sqrt(n))
        out["shortfall_relative_halfwidth"] = half / mean_short
    if stochastic and out["zero_sample_variance"]:
        out["note"] = out.get("note", "") + " Zero sampled variance in a stochastic model does not demonstrate convergence."
    return out


def simulate(sim: Simulator, seed: int, initial=1000, maximum=100000, rtol=.01,
             progress: Callable[[int], None] | None = None, event_preview=True):
    if not 2 <= initial <= maximum <= 100000 or type(initial) is not int or type(maximum) is not int:
        raise ValueError("Require 2 <= initial <= maximum <= 100000.")
    if not 0 < rtol <= 1:
        raise ValueError("Invalid convergence tolerance.")
    values = {key: [] for key in ("efficiency", "delivered", "shortfall", "buffer_end")}
    if sim.crews:
        values["crew_utilisation"] = []
    extra = ("lost", "recovered", "deferred") if sim.features else ()
    if sim.economics:
        extra += ("lost_value",)
    for key in extra:
        values[key] = []
    totals = {k: Counter() for k in ("asset_availability", "mode_downtime", "failures", "loss_groups")}
    periods, balance_worst = {}, 0.0
    events = []
    convergence = []
    limit = initial
    converged = False
    stochastic = bool(sim.modes or sim.standby)
    while True:
        for i in range(len(values["efficiency"]), limit):
            if progress and i % 10 == 0:
                progress(i)
            result = sim.replay(seed, i)
            for key, samples in values.items():
                samples.append(result[key])
            for key, total in totals.items():
                total.update(result[key])
            events.append(sum(result["failures"].values()))
            for label, data in result.get("periods", {}).items():
                periods.setdefault(label, Counter()).update(data)
            if "balance" in result:
                balance_worst = max(balance_worst, abs(result["balance"]["residual"]))
        stats = summary(values["efficiency"])
        # Zero observed variability alone cannot certify a stochastic model.
        converged = (not (sim.modes or sim.standby) or stats["halfwidth"] > 0) and (
            stats["halfwidth"] <= rtol * abs(stats["mean"])
        )
        convergence.append({"n": limit, "mean": stats["mean"], "halfwidth": stats["halfwidth"]})
        if converged or limit == maximum:
            break
        limit = min(maximum, limit * 2)
    if progress:
        progress(limit)
    if converged:
        stop = "converged: 95% mean half-width within relative tolerance"
    elif stochastic and stats["halfwidth"] == 0:
        stop = "replication cap reached with zero sampled variance (convergence not demonstrated)"
    else:
        stop = "replication cap reached before the tolerance was met"
    output = {"seed": seed, "n": limit, "converged": converged, "relative_tolerance": rtol,
              "convergence": convergence, "metrics": {k: summary(v) for k, v in values.items()},
              "contributors": {k: {a: b / limit for a, b in sorted(v.items(), key=lambda x: (-x[1], x[0]))}
                               for k, v in totals.items()},
              "preview": sim.replay(seed, 0, True) if event_preview else None}
    output["stop_reason"] = stop
    output["diagnostics"] = diagnostics(values["efficiency"], values["shortfall"], events, stochastic)
    if sim.features:
        output["balance_max_abs_residual"] = balance_worst
        if periods:
            output["periods_mean"] = {k: {f: x / limit for f, x in v.items()} for k, v in sorted(periods.items())}
        if sim.economics:
            output["economics"] = {k: v for k, v in sim.economics.items()}
    return output
