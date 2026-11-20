"""Directed single-product flow with inventory nodes, routing priorities, yields and recycles.

Solved as a sequence of lexicographic linear programmes (SciPy HiGHS):

1. maximise contractual delivery up to the demand rate;
2. (deferral policy only) maximise catch-up delivery up to the recovery rate;
3. (inventory) maximise total inventory fill, then each buffer in listed order;
4. (routing priorities) maximise flow on priority-1 edges, then priority 2, ...;
5. (declared recycle edges) minimise recycle flow so no spurious circulation remains.

Each stage fixes the optimum of the previous one. For a model with at most one
buffer and none of the 0.3 features, the column layout and the two LP calls are
identical to 0.2 alpha, so legacy results are reproduced exactly.
"""
from dataclasses import dataclass
from functools import lru_cache
from math import inf, isfinite

import numpy as np
from scipy.optimize import linprog

EPS = 1e-8
_TOL = 1e-12  # slack when fixing an earlier LP optimum (scaled by max(1, |optimum|))


def number(value, name, minimum=0):
    if type(value) not in (int, float) or not isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}.")
    return float(value)


@dataclass(frozen=True)
class Buffer:
    node: str
    capacity: float
    initial: float
    fill: float
    draw: float
    id: str = "buffer"


@dataclass(frozen=True)
class FlowState:
    delivered: float          # contractual delivery rate (<= demand)
    catchup: float            # recovery delivery rate above demand
    nets: tuple               # net fill rate per buffer (negative = draw)
    flow: tuple               # edge flows
    supply: float             # source inflow rate
    losses: float             # yield losses rate

    @property
    def net(self):
        return sum(self.nets)


class Flow:
    """Maximise demand served, then catch-up, then refill inventory, then route by priority."""

    def __init__(self, model):
        if "products" in model:
            raise ValueError("Multiple products are outside this engine's scope (single product per model).")
        self.source, self.sink = model["source"], model["sink"]
        self.target = number(model["target"], "target", EPS)
        self.feed = number(model.get("feed", self.target), "feed")
        if self.source == self.sink:
            raise ValueError("Source and sink must be distinct.")
        self.edges = tuple(model["edges"])
        self.ids = tuple(e["id"] for e in self.edges)
        if not self.edges or len(set(self.ids)) != len(self.ids):
            raise ValueError("Edges require distinct IDs.")
        self.capacity = tuple(number(e["capacity"], e["id"]) for e in self.edges)
        self.yields = tuple(number(e.get("yield", 1.0), f"{e['id']} yield", EPS) for e in self.edges)
        if any(y > 1 for y in self.yields):
            raise ValueError("Edge yield must be in (0, 1].")
        if "buffer" in model and "buffers" in model:
            raise ValueError("Use either buffer or buffers, not both.")
        raw = ([dict(model["buffer"], id="buffer")] if model.get("buffer") else list(model.get("buffers", [])))
        self.buffers = tuple(Buffer(b["node"], *(number(b[k], f"{b.get('id', 'buffer')} {k}")
                                                  for k in ("capacity", "initial", "fill", "draw")),
                                    id=b.get("id", "buffer")) for b in raw)
        if len({b.id for b in self.buffers}) != len(self.buffers) or len({b.node for b in self.buffers}) != len(self.buffers):
            raise ValueError("Buffers need distinct IDs and nodes.")
        for b in self.buffers:
            if b.capacity <= 0 or b.initial > b.capacity:
                raise ValueError("Invalid storage capacity or initial inventory.")
        self.buffer = self.buffers[0] if len(self.buffers) == 1 else None
        nodes = {e[k] for e in self.edges for k in ("from", "to")}
        if not {self.source, self.sink} <= nodes or any(
            b.node not in nodes or b.node in (self.source, self.sink) for b in self.buffers
        ):
            raise ValueError("Source, sink or buffer node is missing or invalid.")
        recycle = model.get("recycle_edges", [])
        if not set(recycle) <= set(self.ids) or len(set(recycle)) != len(recycle):
            raise ValueError("Recycle edges must be distinct existing edge IDs.")
        self.recycle = tuple(self.ids.index(r) for r in recycle)
        ordered = {n: [] for n in nodes}
        for e in self.edges:
            if e["from"] == self.sink or e["to"] == self.source:
                raise ValueError("Edges cannot enter the source or leave the sink.")
            ordered[e["from"]].append(e["to"])
        reachable = self._reachable(ordered, self.source)
        reverse = {n: [] for n in nodes}
        for a, targets in ordered.items():
            for b in targets:
                reverse[b].append(a)
        if reachable != nodes or self._reachable(reverse, self.sink) != nodes:
            raise ValueError("All flow nodes must belong to a source-to-sink path.")
        # Without declared recycle edges the graph must be acyclic.
        forward = {n: [] for n in nodes}
        for i, e in enumerate(self.edges):
            if i not in self.recycle:
                forward[e["from"]].append(e["to"])
        indegree = {n: 0 for n in nodes}
        for targets in forward.values():
            for b in targets:
                indegree[b] += 1
        pending = [n for n in nodes if not indegree[n]]
        count = 0
        while pending:
            n = pending.pop()
            count += 1
            for b in forward[n]:
                indegree[b] -= 1
                if not indegree[b]:
                    pending.append(b)
        if count != len(nodes):
            raise ValueError("Recycle flow is outside this engine's scope unless every cycle is broken by "
                             "declared recycle_edges with explicit capacities.")
        self.deferral = model.get("deferral") is not None
        # Column layout: edges, supply, delivery, [catch-up], buffer nets (one dummy column if no buffer).
        self.c_supply = len(self.edges)
        self.c_delivery = self.c_supply + 1
        self.c_catchup = self.c_delivery + 1 if self.deferral else None
        first_buffer = self.c_delivery + (2 if self.deferral else 1)
        self.c_buffers = tuple(range(first_buffer, first_buffer + max(1, len(self.buffers))))
        ncols = self.c_buffers[-1] + 1
        self.ncols = ncols
        self.balance = np.zeros((len(nodes), ncols))
        index = {n: i for i, n in enumerate(sorted(nodes))}
        for i, edge in enumerate(self.edges):
            self.balance[index[edge["from"]], i] -= 1
            self.balance[index[edge["to"]], i] += self.yields[i]
        self.balance[index[self.source], self.c_supply] = 1
        self.balance[index[self.sink], self.c_delivery] = -1
        if self.deferral:
            self.balance[index[self.sink], self.c_catchup] = -1
        for b, column in zip(self.buffers, self.c_buffers):
            self.balance[index[b.node], column] = -1
        fraction_rows = []
        for group in model.get("splits", []):
            members = [(self.ids.index(k), number(v, "split fraction")) for k, v in group.items()]
            if len(members) < 2 or abs(sum(v for _, v in members) - 1) > EPS:
                raise ValueError("A split must have at least two branches summing to one.")
            branches = {i for i, _ in members}
            origin = self.edges[members[0][0]]["from"]
            if branches != {i for i, e in enumerate(self.edges) if e["from"] == origin}:
                raise ValueError("A split must specify all outbound edges at one node.")
            for i, proportion in members:
                row = np.zeros(ncols)
                row[list(branches)] -= proportion
                row[i] += 1
                fraction_rows.append(row)
        if fraction_rows:
            self.balance = np.vstack((self.balance, fraction_rows))
        priorities = {}
        for i, e in enumerate(self.edges):
            if "priority" in e:
                p = e["priority"]
                if type(p) is not int or p < 1:
                    raise ValueError(f"{e['id']}: routing priority must be a positive integer.")
                priorities.setdefault(p, []).append(i)
        self.priorities = tuple(tuple(priorities[p]) for p in sorted(priorities))
        self.zero = np.zeros(len(self.balance))
        self._solve = lru_cache(maxsize=4096)(self._uncached_solve)

    @staticmethod
    def _reachable(graph, start):
        seen, pending = set(), [start]
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(graph[node])
        return seen

    def modes(self, levels):
        if isinstance(levels, (int, float)):
            levels = (levels,)
        return tuple("empty" if level <= EPS else "full" if level >= b.capacity - EPS else "intermediate"
                     for b, level in zip(self.buffers, levels))

    def solve(self, capacity, level, target, feed=None, catchup=0.0):
        """Legacy signature returns (delivered, net, edge flow); see solve_state for full detail."""
        state = self.solve_state(capacity, level, target, feed, catchup)
        return state.delivered, state.net, state.flow

    def solve_state(self, capacity, levels, target, feed=None, catchup=0.0):
        mode = self.modes(levels) if self.buffers else ("none",)
        return self._solve(tuple(capacity), mode, target, self.feed if feed is None else feed, catchup)

    def _lp(self, objective, bounds, rows, limits):
        kwargs = {"A_ub": np.array(rows), "b_ub": np.array(limits)} if rows else {}
        result = linprog(objective, A_eq=self.balance, b_eq=self.zero, bounds=bounds, method="highs", **kwargs)
        if not result.success:
            raise ValueError(f"Flow solve failed: {result.message}")
        return result

    def _uncached_solve(self, capacity, mode, target, feed, catchup):
        bounds = [(0, cap) for cap in capacity] + [(0, feed), (0, target)]
        if self.deferral:
            bounds.append((0, catchup))
        if self.buffers:
            for b, m in zip(self.buffers, mode):
                bounds.append((-b.draw if m != "empty" else 0.0, b.fill if m != "full" else 0.0))
        else:
            bounds.append((0.0, 0.0))
        objective = np.zeros(self.ncols)
        objective[self.c_delivery] = -1
        rows, limits = [], []
        result = self._lp(objective, bounds, rows, limits)
        delivered = min(target, max(0.0, float(result.x[self.c_delivery])))
        caught = 0.0
        later = self.deferral or self.buffers or self.priorities or self.recycle
        if later:
            bounds[self.c_delivery] = (delivered, delivered)
        if self.deferral and catchup > 0:
            objective = np.zeros(self.ncols)
            objective[self.c_catchup] = -1
            result = self._lp(objective, bounds, rows, limits)
            caught = min(catchup, max(0.0, float(result.x[self.c_catchup])))
            bounds[self.c_catchup] = (caught, caught)
        if self.buffers:
            objective = np.zeros(self.ncols)
            objective[list(self.c_buffers)] = -1
            result = self._lp(objective, bounds, rows, limits)
            if len(self.buffers) > 1:
                total = float(result.x[list(self.c_buffers)].sum())
                row = np.zeros(self.ncols)
                row[list(self.c_buffers)] = -1
                rows, limits = rows + [row], limits + [-(total - _TOL * max(1.0, abs(total)))]
                for column in self.c_buffers:
                    objective = np.zeros(self.ncols)
                    objective[column] = -1
                    result = self._lp(objective, bounds, rows, limits)
                    row = np.zeros(self.ncols)
                    row[column] = -1
                    value = float(result.x[column])
                    rows, limits = rows + [row], limits + [-(value - _TOL * max(1.0, abs(value)))]
        for group in self.priorities:
            objective = np.zeros(self.ncols)
            objective[list(group)] = -1
            result = self._lp(objective, bounds, rows, limits)
            row = np.zeros(self.ncols)
            row[list(group)] = -1
            value = float(result.x[list(group)].sum())
            rows, limits = rows + [row], limits + [-(value - _TOL * max(1.0, abs(value)))]
        if self.recycle and later:
            if self.buffers:
                # Hold each buffer's net at its optimum while removing circulation.
                for column in self.c_buffers:
                    value = float(result.x[column])
                    bounds[column] = (min(value, bounds[column][1]), min(value, bounds[column][1]))
            objective = np.zeros(self.ncols)
            objective[list(self.recycle)] = 1
            result = self._lp(objective, bounds, rows, limits)
        x = result.x
        flow = tuple(float(v) for v in x[:len(self.edges)])
        nets = tuple(float(x[c]) for c in self.c_buffers) if self.buffers else (float(x[self.c_buffers[0]]),)
        losses = sum((1 - y) * f for y, f in zip(self.yields, flow))
        return FlowState(delivered, caught, nets, flow, float(x[self.c_supply]), losses)

    def next_boundary(self, level, net):
        """Time until any buffer reaches empty or full (legacy scalar or per-buffer tuples)."""
        if isinstance(level, (int, float)):
            level, net = (level,), (net,)
        best = inf
        for b, x, n in zip(self.buffers, level, net):
            if n > EPS:
                best = min(best, max(0.0, (b.capacity - x) / n))
            elif n < -EPS:
                best = min(best, max(0.0, -x / n))
        return best
