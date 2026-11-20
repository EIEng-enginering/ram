"""Command-based model editing with undo/redo, shared selection and a reviewable change list.

Every edit is a JSON-serialisable command applied to a deep copy of the model.
Edits to an approved baseline require explicit confirmation. Intermediate drafts
may be incomplete; ``issues`` reports what the engine would reject, so the user
sees why a draft cannot yet run instead of having it silently repaired.
"""
from copy import deepcopy
from datetime import UTC, datetime

from .study import digest

COMMANDS = {"add_asset", "remove_asset", "add_edge", "remove_edge", "set", "add_dependency",
            "remove_dependency", "add_mode", "remove_mode", "set_buffer", "add_annotation", "set_rbd",
            "add_standby_group", "replace_model"}


class BaselineChangeError(PermissionError):
    """Raised when an approved baseline would change without confirmation."""


def _find(items, key, kind):
    for item in items:
        if item.get("id") == key:
            return item
    raise ValueError(f"Unknown {kind} {key}.")


def _apply(model, command):
    kind = command.get("op")
    if kind not in COMMANDS:
        raise ValueError(f"Unsupported edit {kind}.")
    m = deepcopy(model)
    m.setdefault("assets", [])
    m.setdefault("edges", [])
    if kind == "add_asset":
        key = command["id"]
        if any(a["id"] == key for a in m["assets"]):
            raise ValueError(f"Asset {key} exists.")
        asset = {"id": key, "modes": deepcopy(command.get("modes", []))}
        if command.get("explicit_no_failures"):
            asset["explicit_no_failures"] = True
        if command.get("equipment_id"):
            asset["equipment_id"] = command["equipment_id"]
        m["assets"].append(asset)
    elif kind == "remove_asset":
        key = command["id"]
        _find(m["assets"], key, "asset")
        users = [e["id"] for e in m["edges"] if key in e.get("assets", [])] + [
            a["id"] for a in m["assets"] if key in a.get("requires", [])]
        if users:
            raise ValueError(f"{key} is still used by {', '.join(users)}; remove those links first.")
        m["assets"] = [a for a in m["assets"] if a["id"] != key]
        for prefix in (f"assets/{key}", f"modes/{key}/", f"dependencies/{key}/", f"standby/{key}"):
            for p in [p for p in m.get("provenance", {}) if p == prefix or p.startswith(prefix)]:
                del m["provenance"][p]
    elif kind == "add_edge":
        edge = {k: deepcopy(command[k]) for k in ("id", "from", "to", "capacity")}
        edge["assets"] = list(command.get("assets", []))
        for extra in ("priority", "yield"):
            if extra in command:
                edge[extra] = command[extra]
        if any(e["id"] == edge["id"] for e in m["edges"]):
            raise ValueError(f"Edge {edge['id']} exists.")
        unknown = set(edge["assets"]) - {a["id"] for a in m["assets"]}
        if unknown:
            raise ValueError(f"Unknown assets on edge: {', '.join(sorted(unknown))}.")
        m["edges"].append(edge)
    elif kind == "remove_edge":
        _find(m["edges"], command["id"], "edge")
        m["edges"] = [e for e in m["edges"] if e["id"] != command["id"]]
        m.get("provenance", {}).pop(f"edges/{command['id']}", None)
    elif kind == "set":
        group, key, field = command["target"]
        if group not in ("assets", "edges"):
            raise ValueError("Property edits target assets or edges.")
        if field == "id":
            raise ValueError("Rename by removing and re-adding to keep references explicit.")
        item = _find(m[group], key, group[:-1])
        if command.get("value") is None:
            item.pop(field, None)
        else:
            item[field] = deepcopy(command["value"])
    elif kind in ("add_dependency", "remove_dependency"):
        child = _find(m["assets"], command["asset"], "asset")
        _find(m["assets"], command["requires"], "asset")
        parents = child.setdefault("requires", [])
        if kind == "add_dependency":
            if command["requires"] in parents or command["requires"] == child["id"]:
                raise ValueError("Duplicate or self dependency.")
            parents.append(command["requires"])
        else:
            parents.remove(command["requires"])
            m.get("provenance", {}).pop(f"dependencies/{child['id']}/{command['requires']}", None)
        if "requires_k" in command:
            child["requires_k"] = command["requires_k"]
    elif kind == "add_mode":
        asset = _find(m["assets"], command["asset"], "asset")
        mode = deepcopy(command["mode"])
        if any(x["id"] == mode["id"] for x in asset["modes"]):
            raise ValueError("Duplicate mode.")
        asset["modes"].append(mode)
        asset.pop("explicit_no_failures", None)
    elif kind == "remove_mode":
        asset = _find(m["assets"], command["asset"], "asset")
        _find(asset["modes"], command["mode"], "mode")
        asset["modes"] = [x for x in asset["modes"] if x["id"] != command["mode"]]
        m.get("provenance", {}).pop(f"modes/{asset['id']}/{command['mode']}", None)
    elif kind == "set_buffer":
        key = command["id"]
        if key == "buffer" and "buffers" not in m:
            if command.get("value"):
                m["buffer"] = deepcopy(command["value"])
            else:
                m.pop("buffer", None)
        else:
            buffers = [b for b in m.get("buffers", []) if b.get("id") != key]
            if command.get("value"):
                buffers.append({"id": key, **deepcopy(command["value"])})
            if buffers:
                m["buffers"] = buffers
            else:
                m.pop("buffers", None)
    elif kind == "add_annotation":
        m.setdefault("annotations", []).append({"target": command["target"], "text": command["text"]})
    elif kind == "set_rbd":
        m["rbd"] = deepcopy(command["tree"])
    elif kind == "replace_model":
        # Expert JSON edit: the whole model is replaced and recorded as one reviewable change.
        m = deepcopy(command["model"])
    elif kind == "add_standby_group":
        m.setdefault("standby_groups", []).append(deepcopy(command["group"]))
    return m


class ModelEditor:
    def __init__(self, model, approved_hash=None, validator=None):
        self.model = deepcopy(model)
        self.approved_hash = approved_hash
        self.validator = validator
        self.undo_stack, self.redo_stack, self.changes = [], [], []
        self.selection = None
        self.listeners = []

    # Selection is shared by every view that subscribes.
    def select(self, key):
        self.selection = key
        for listener in list(self.listeners):
            listener(key)

    def issues(self):
        if not self.validator:
            return []
        try:
            self.validator(self.model)
        except (ValueError, KeyError, TypeError) as error:
            return [str(error)]
        return []

    def apply(self, command, actor="desktop user", confirm_baseline=False):
        before = digest(self.model)
        if self.approved_hash is not None and before == self.approved_hash and not confirm_baseline:
            raise BaselineChangeError("This edit changes the approved baseline. Confirm explicitly to create a new "
                                      "unapproved revision.")
        updated = _apply(self.model, command)
        self.undo_stack.append(self.model)
        self.redo_stack.clear()
        self.model = updated
        self.changes.append({"n": len(self.changes) + 1, "op": command["op"], "command": deepcopy(command),
                             "before": before, "after": digest(updated), "actor": actor,
                             "at": datetime.now(UTC).isoformat(), "kind": "edit"})
        return updated

    def undo(self, actor="desktop user"):
        if not self.undo_stack:
            raise ValueError("Nothing to undo.")
        before = digest(self.model)
        self.redo_stack.append(self.model)
        self.model = self.undo_stack.pop()
        self.changes.append({"n": len(self.changes) + 1, "op": "undo", "before": before, "after": digest(self.model),
                             "actor": actor, "at": datetime.now(UTC).isoformat(), "kind": "undo"})
        return self.model

    def redo(self, actor="desktop user"):
        if not self.redo_stack:
            raise ValueError("Nothing to redo.")
        before = digest(self.model)
        self.undo_stack.append(self.model)
        self.model = self.redo_stack.pop()
        self.changes.append({"n": len(self.changes) + 1, "op": "redo", "before": before, "after": digest(self.model),
                             "actor": actor, "at": datetime.now(UTC).isoformat(), "kind": "redo"})
        return self.model

    def change_list(self):
        """Readable list of net edits for review."""
        lines = []
        for c in self.changes:
            detail = {k: v for k, v in c.get("command", {}).items() if k != "op"}
            lines.append(f"{c['n']}. {c['op']} {detail if detail else ''} [{c['before'][:8]} -> {c['after'][:8]}] by {c['actor']}")
        return lines

    def save(self, db, actor, note="Edited in model editor"):
        """Persist the model and its edit log as an audited revision."""
        from .study import _audit, save_model
        fingerprint = save_model(db, self.model, actor, note)
        for c in self.changes:
            _audit(db, c["after"], f"model {c['kind']}", c["actor"],
                   f"{c['op']} {c.get('command', '')} from {c['before']}")
        self.changes = []
        return fingerprint
