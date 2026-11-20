"""Build an entirely synthetic, importable equipment library."""
from .example import SOURCE, offshore_extended

FIELDS = {"mtbf": ("mtbf_hours", "h"), "logistics": ("logistics_hours", "h"),
          "mobilisation": ("mobilisation_hours", "h"), "repair": ("active_repair_hours", "h"),
          "loss": ("capacity_loss_fraction", "fraction")}


def equipment_fixture():
    rows = {"source": [(2, ["EXAMPLE", "example", SOURCE, None, "1"])],
            "subsystem": [(2, ["offshore", None, "Synthetic offshore module"])],
            "equipment": [], "failure_mode": [], "mode_value": []}
    for i, asset in enumerate(offshore_extended()["assets"], 2):
        tag = asset["id"]
        rows["equipment"].append((i, [tag, "offshore", tag, tag.split("-")[0]]))
        for mode in asset["modes"]:
            mode_id = f"{tag}-{mode['id']}"
            rows["failure_mode"].append((i, [mode_id, tag, "Trip", "revealed", mode["distribution"], "calendar"]))
            for j, (source, (name, units)) in enumerate(FIELDS.items()):
                value = mode[source]
                rows["mode_value"].append((i * 10 + j, [
                    mode_id, name, value, "EXAMPLE", f"synthetic fixture {tag}/{source}",
                    str(value), units, "unreviewed", "unassessed", None, None, None,
                    "synthetic", "Synthetic offshore example only"]))
    return rows
