"""Configurable mapping of third-party CSV/XLSX reliability tables into the library.

A mapping is a JSON document (schema ``rammodel-mapping-1``)::

    {"schema": "rammodel-mapping-1",
     "sheet": "Data",                      # XLSX only; ignored for CSV
     "header_row": 1,                      # 1-based
     "source": {"id": "OREDA-X", "kind": "licensed", "citation": "...", "revision": "6"},
     "subsystem": {"id": "process", "name": "Process"},
     "columns": {"tag": "Tag", "equipment_class": "Class", "mode": "Failure mode",
                 "detection": "Detection", "distribution": "Distribution", "exposure": "Exposure"},
     "values": [{"field": "mtbf_hours", "column": "MTBF", "unit_column": "MTBF unit"},
                {"field": "active_repair_hours", "column": "MTTR", "unit": "h"}],
     "applicability": {"column": "Applicability"} | {"text": "..."} | null,
     "basis": "stated" | "inferred",
     "duplicates": "reject" | "keep_first"}

``preview`` never writes. It returns staged rows with the original cell text,
unit, row number and column for every value, plus row-specific errors and
warnings. ``apply_mapping`` writes only an error-free preview, atomically,
inside one savepoint, together with an import batch record.
"""
import csv
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from .exchange import import_exchange
from .units import FIELD_DIMENSIONS, UnitError, to_canonical

SCHEMA = "rammodel-mapping-1"
_REQUIRED_COLUMNS = ("tag", "equipment_class", "mode", "detection", "distribution", "exposure")
_CHOICES = {"detection": {"revealed", "hidden", "unresolved"},
            "distribution": {"exponential", "weibull", "lognormal", "unresolved"},
            "exposure": {"operating", "calendar", "unresolved"}}


def _cells(path: Path, mapping):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [list(r) for r in csv.reader(handle)]
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Mapped import supports .csv and .xlsx files.")
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        ws = book[mapping["sheet"]] if mapping.get("sheet") else book.worksheets[0]
        rows = []
        for cells in ws.iter_rows():
            if any(c.data_type in ("f", "e") for c in cells):
                raise ValueError(f"Formula or error cell in row {cells[0].row}; export values before import.")
            rows.append([c.value for c in cells])
        return rows
    finally:
        book.close()


def validate_mapping(mapping):
    if not isinstance(mapping, dict) or mapping.get("schema") != SCHEMA:
        raise ValueError(f"Mapping must declare schema {SCHEMA}.")
    columns = mapping.get("columns", {})
    missing = [k for k in _REQUIRED_COLUMNS if k not in columns]
    if missing:
        raise ValueError(f"Mapping lacks columns for: {', '.join(missing)}.")
    source = mapping.get("source", {})
    if not {"id", "kind", "citation"} <= source.keys():
        raise ValueError("Mapping source needs id, kind and citation.")
    if source["kind"] not in {"site", "vendor", "licensed", "judgement", "example"}:
        raise ValueError("Unsupported source kind.")
    if not mapping.get("values"):
        raise ValueError("Map at least one reliability value.")
    for item in mapping["values"]:
        if item.get("field") not in FIELD_DIMENSIONS:
            raise ValueError(f"Unknown library field {item.get('field')}.")
        if "column" not in item or ("unit" in item) == ("unit_column" in item):
            raise ValueError(f"{item['field']}: give a value column and exactly one of unit or unit_column.")
    if mapping.get("basis", "stated") not in {"stated", "inferred"}:
        raise ValueError("Mapped values are stated or inferred; estimates come from observations.")
    if mapping.get("duplicates", "reject") not in {"reject", "keep_first"}:
        raise ValueError("Duplicate policy must be reject or keep_first.")
    return mapping


def _column_letter(index):
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def preview(path: Path, mapping):
    """Stage a mapped file. Returns rows, errors, warnings and staged tables."""
    mapping = validate_mapping(mapping)
    raw = _cells(Path(path), mapping)
    header_row = mapping.get("header_row", 1)
    if len(raw) < header_row:
        raise ValueError("The file has no header row.")
    header = [str(h).strip() if h is not None else "" for h in raw[header_row - 1]]
    position = {}
    wanted = list(mapping["columns"].values()) + [v["column"] for v in mapping["values"]] + [
        v["unit_column"] for v in mapping["values"] if "unit_column" in v]
    applicability = mapping.get("applicability") or {}
    if "column" in applicability:
        wanted.append(applicability["column"])
    for name in wanted:
        if name not in header:
            raise ValueError(f"Column '{name}' is not in the header row {header_row}.")
        if header.count(name) > 1:
            raise ValueError(f"Column '{name}' appears more than once in the header.")
        position[name] = header.index(name)
    source, subsystem = mapping["source"], mapping.get("subsystem", {"id": "imported", "name": "Imported"})
    errors, warnings, rows = [], [], []
    equipment, modes, values, seen = {}, {}, [], {}
    units_seen = {}
    for n, row in enumerate(raw[header_row:], header_row + 1):
        if all(c in (None, "") or (isinstance(c, str) and not c.strip()) for c in row):
            continue
        row = list(row) + [None] * (len(header) - len(row))

        def cell(name):
            value = row[position[name]]
            return value.strip() if isinstance(value, str) else value

        def where(name):
            return f"{_column_letter(position[name])}{n}"

        text = {k: cell(c) for k, c in mapping["columns"].items()}
        row_errors = []
        for key in _REQUIRED_COLUMNS:
            if text[key] in (None, ""):
                row_errors.append((where(mapping["columns"][key]), f"{key} is blank"))
            elif key in _CHOICES and str(text[key]).lower() not in _CHOICES[key]:
                row_errors.append((where(mapping["columns"][key]), f"{key} '{text[key]}' not one of {sorted(_CHOICES[key])}"))
        tag = str(text["tag"]) if text["tag"] not in (None, "") else None
        mode_id = f"{tag}/{text['mode']}" if tag and text["mode"] else None
        staged_values = []
        for item in mapping["values"]:
            raw_value = cell(item["column"])
            unit = item.get("unit") or cell(item["unit_column"])
            locator = f"{Path(path).name}!{mapping.get('sheet') or ''}{'!' if mapping.get('sheet') else ''}{where(item['column'])}"
            if raw_value in (None, ""):
                # Missing stays missing: no row is written for a blank cell.
                rows.append({"row": n, "field": item["field"], "status": "missing", "cell": where(item["column"])})
                continue
            try:
                quantity = to_canonical(raw_value, unit, FIELD_DIMENSIONS[item["field"]])
            except UnitError as error:
                row_errors.append((where(item["column"]), f"{item['field']}: {error}"))
                continue
            if quantity.value < 0 or (item["field"] == "capacity_loss_fraction" and quantity.value > 1):
                row_errors.append((where(item["column"]), f"{item['field']}: value outside its valid range"))
                continue
            if quantity.value == 0 and item["field"] not in ("logistics_hours", "mobilisation_hours",
                                                             "active_repair_hours", "capacity_loss_fraction"):
                row_errors.append((where(item["column"]), f"{item['field']}: zero is invalid for this field"))
                continue
            units_seen.setdefault(item["field"], set()).add(quantity.original_unit)
            status = "zero" if quantity.value == 0 else ("synthetic" if source["kind"] == "example" else
                                                        mapping.get("basis", "stated"))
            rows.append({"row": n, "field": item["field"], "status": status, "cell": where(item["column"]),
                         "original": quantity.original_value, "unit": quantity.original_unit,
                         "canonical": quantity.value, "canonical_unit": quantity.unit})
            staged_values.append((item["field"], quantity, locator))
        appl = applicability.get("text") if "text" in applicability else (
            cell(applicability["column"]) if "column" in applicability else None)
        if row_errors:
            errors.extend({"row": n, "cell": c, "message": m} for c, m in row_errors)
            continue
        key = (tag, str(text["mode"]))
        if key in seen:
            message = f"duplicate equipment/mode {tag}/{text['mode']} (first at row {seen[key]})"
            if mapping.get("duplicates", "reject") == "reject":
                errors.append({"row": n, "cell": where(mapping["columns"]["tag"]), "message": message})
            else:
                warnings.append({"row": n, "message": message + "; kept first"})
            continue
        seen[key] = n
        if tag in equipment and equipment[tag][1][3] != str(text["equipment_class"]):
            errors.append({"row": n, "cell": where(mapping["columns"]["equipment_class"]),
                           "message": f"equipment {tag} has conflicting classes"})
            continue
        equipment.setdefault(tag, (n, [tag, subsystem["id"], tag, str(text["equipment_class"])]))
        modes[mode_id] = (n, [mode_id, tag, str(text["mode"]), str(text["detection"]).lower(),
                              str(text["distribution"]).lower(), str(text["exposure"]).lower()])
        for field, quantity, locator in staged_values:
            values.append((n, [mode_id, field, quantity.value, source["id"], locator, quantity.original_value,
                               quantity.original_unit, "unreviewed", "unassessed", None, None, None,
                               "synthetic" if source["kind"] == "example" else mapping.get("basis", "stated"),
                               None if appl in (None, "") else str(appl)]))
    for field, units in units_seen.items():
        if len(units) > 1:
            warnings.append({"row": None, "message": f"mixed units for {field}: {', '.join(sorted(units))} "
                                                     "(each converted to canonical units; confirm the column basis)"})
    staged = {"source": [(header_row, [source["id"], source["kind"], source["citation"],
                                       source.get("document_sha256"), source.get("revision")])],
              "subsystem": [(header_row, [subsystem["id"], subsystem.get("parent"), subsystem["name"]])],
              "equipment": sorted(equipment.values()), "failure_mode": sorted(modes.values()),
              "mode_value": values}
    return {"file": Path(path).name, "sha256": sha256(Path(path).read_bytes()).hexdigest(),
            "mapping": mapping, "rows": rows, "errors": errors, "warnings": warnings, "staged": staged}


def apply_mapping(db, staged_preview, actor):
    """Apply an error-free preview atomically and record the import batch."""
    if staged_preview["errors"]:
        raise ValueError(f"Resolve {len(staged_preview['errors'])} row errors before applying.")
    if not actor.strip():
        raise ValueError("Enter an audit actor.")
    batch = uuid4().hex
    savepoint = "mapping_" + batch
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        warnings = import_exchange(db, staged_preview["staged"], actor, apply=True, batch=batch)
        db.execute("INSERT INTO import_batch VALUES (?,?,?,?,?,?,?,?)",
                   (batch, actor.strip(), datetime.now(UTC).isoformat(), staged_preview["file"],
                    staged_preview["sha256"], json.dumps(staged_preview["mapping"], sort_keys=True),
                    len(staged_preview["staged"]["mode_value"]),
                    json.dumps({"warnings": staged_preview["warnings"] + [{"message": w} for w in warnings]})))
    except BaseException:
        db.execute(f"ROLLBACK TO {savepoint}")
        db.execute(f"RELEASE {savepoint}")
        raise
    db.execute(f"RELEASE {savepoint}")
    return batch, warnings
