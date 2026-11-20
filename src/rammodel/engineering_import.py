"""Neutral process handoff adapter. Reader integrations should map into this contract."""
from copy import deepcopy


def import_topology(payload, study_basis):
    """Lift confirmed flow edges and park unresolved drawing paths for review.

    Drawing connectivity describes physical topology. Every RAM capacity and
    equipment contribution therefore remains a draft until the study review.
    """
    if payload.get("schema") != "rammodel-topology-1":
        raise ValueError("A rammodel-topology-1 mapped graph is required.")
    model = deepcopy(study_basis)
    model.update(assets=[], edges=[], unresolved=[], provenance={})
    source = payload["source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Specify a drawing or register reference.")
    nodes = set(payload["nodes"])
    seen_assets, seen_edges = set(), set()
    for asset in payload["equipment"]:
        tag = asset["tag"]
        if not tag or tag in seen_assets or not asset["locator"]:
            raise ValueError("Each asset needs a unique tag and source locator.")
        seen_assets.add(tag)
        model["assets"].append({"id": tag, "equipment_id": asset.get("equipment_id", tag), "modes": []})
        model["provenance"][f"assets/{tag}"] = {"source": source, "locator": asset["locator"]}
    for edge in payload["flow"]:
        edge_id = edge["id"]
        if not edge_id or edge_id in seen_edges or not edge["locator"]:
            raise ValueError("Each connection needs a unique ID and source locator.")
        seen_edges.add(edge_id)
        if (edge.get("confirmed") is not True or edge.get("capacity") is None or
                not {edge.get("from"), edge.get("to")} <= nodes or not set(edge.get("assets", [])) <= seen_assets):
            model["unresolved"].append(f"{edge_id}: confirm connectivity, equipment and capacity ({edge['locator']}).")
            continue
        model["edges"].append({k: deepcopy(edge[k]) for k in ("id", "from", "to", "assets", "capacity")})
        model["provenance"][f"edges/{edge_id}"] = {"source": source, "locator": edge["locator"]}
    model["provenance"].update(study_basis.get("provenance", {}))
    return model
