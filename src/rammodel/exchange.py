"""Staged, source-preserving equipment and failure data exchange."""
import csv
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from openpyxl import Workbook, load_workbook

TABLES = {
    "source": ("id", "kind", "citation", "document_sha256", "revision"),
    "subsystem": ("id", "parent_id", "name"),
    "equipment": ("id", "subsystem_id", "tag", "equipment_class"),
    "failure_mode": ("id", "equipment_id", "name", "detection", "distribution", "exposure_basis"),
    "mode_value": ("mode_id", "field", "value", "source_id", "source_locator", "original_value",
                   "original_unit", "review_state", "uncertainty", "low", "high", "error_factor",
                   "value_basis", "applicability"),
}
# Exchange files written by 0.2 alpha lack the last two mode_value columns.
LEGACY_COLUMNS = {"mode_value": TABLES["mode_value"][:12]}
DEFAULTS = {"value_basis": "stated", "applicability": None}
NUMBER_FIELDS = {"value", "low", "high", "error_factor"}
OPTIONAL = {"document_sha256", "revision", "parent_id", "low", "high", "error_factor", "applicability"}
REQUIRED = {
    "exponential": {"failure_rate_hour", "mtbf_hours"},
    "weibull": {"weibull_shape", "weibull_scale_hours"},
    "lognormal": {"lognormal_median_hours", "lognormal_sigma"},
}
COMMON = {"logistics_hours", "mobilisation_hours", "active_repair_hours", "capacity_loss_fraction"}


def _rows(path: Path):
    if path.is_dir():
        for table in TABLES:
            with (path / f"{table}.csv").open(encoding="utf-8-sig", newline="") as handle:
                yield table, list(csv.reader(handle))
    else:
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            for table in TABLES:
                ws = book[table]
                rows = []
                for cells in ws.iter_rows():
                    if any(c.data_type in ("f", "e") for c in cells):
                        raise ValueError(f"Formulas or error cells are unsupported in {table}.")
                    rows.append([c.value for c in cells])
                yield table, rows
        finally:
            book.close()


def read_exchange(path: Path):
    staged = {}
    for table, rows in _rows(path):
        columns = TABLES[table]
        legacy = False
        if rows and table in LEGACY_COLUMNS and tuple(rows[0]) == LEGACY_COLUMNS[table]:
            columns, legacy = LEGACY_COLUMNS[table], True
        if not rows or tuple(rows[0]) != columns:
            raise ValueError(f"Unexpected header in {table}. Expected: {', '.join(TABLES[table])}")
        target = []
        for n, row in enumerate(rows[1:], 2):
            if all(x in (None, "") for x in row):
                continue
            if len(row) != len(columns):
                raise ValueError(f"{table} row {n}: expected {len(columns)} fields.")
            values = []
            for key, value in zip(columns, row, strict=True):
                if value in (None, ""):
                    if key not in OPTIONAL:
                        raise ValueError(f"{table} row {n}: {key} must be supplied.")
                    value = None
                elif key in NUMBER_FIELDS:
                    try:
                        value = float(value)
                    except (TypeError, ValueError) as error:
                        raise ValueError(f"{table} row {n}: {key} must be numeric.") from error
                else:
                    value = str(value)
                    if path.is_dir() and value.startswith(_CSV_MARK):
                        value = value[len(_CSV_MARK):]
                values.append(value)
            if legacy:
                values.extend(DEFAULTS[k] for k in TABLES[table][len(columns):])
            target.append((n, values))
        staged[table] = target
    return staged


def _validate_database(db):
    warnings = []
    for mode_id, distribution, detection, basis in db.execute(
        "SELECT id, distribution, detection, exposure_basis FROM failure_mode ORDER BY id"
    ):
        records = dict(db.execute("SELECT field,value FROM mode_value WHERE mode_id=?", (mode_id,)))
        found = records.keys()
        expected = REQUIRED.get(distribution, set())
        disallowed = set().union(*REQUIRED.values()) - expected
        if expected and found & disallowed:
            raise ValueError(f"{mode_id}: fields for a different distribution were supplied.")
        proof = "proof_test_hours"
        if detection == "revealed" and proof in found:
            raise ValueError(f"{mode_id}: a revealed failure may not have a proof-test interval.")
        missing = COMMON - found
        if distribution == "exponential":
            if not expected & found:
                missing = missing | {"failure_rate_hour or mtbf_hours"}
            if expected <= found and abs(records["failure_rate_hour"] * records["mtbf_hours"] - 1) > 1e-6:
                raise ValueError(f"{mode_id}: MTBF and failure rate disagree.")
        else:
            missing = missing | (expected - found)
        if detection == "hidden" and proof not in found:
            missing = missing | {proof}
        if missing:
            warnings.append(f"{mode_id}: missing {', '.join(sorted(missing))}")
        if "unresolved" in (distribution, detection, basis):
            warnings.append(f"{mode_id}: unresolved failure model basis")
    parents = dict(db.execute("SELECT id,parent_id FROM subsystem"))
    for node in parents:
        seen = set()
        while node is not None:
            if node in seen:
                raise ValueError(f"Subsystem hierarchy contains a cycle at {node}.")
            seen.add(node)
            node = parents.get(node)
    return warnings


def import_exchange(db, staged, actor, *, apply=False, batch=None):
    """Validate in a savepoint. Applying new rows requires an explicit caller action."""
    if not actor.strip():
        raise ValueError("Enter an audit actor.")
    savepoint = "stage_" + uuid4().hex
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        db.execute("PRAGMA defer_foreign_keys = ON")
        for table, columns in TABLES.items():
            for row, values in staged[table]:
                # Records from imported files must be reviewed locally.
                if table == "mode_value":
                    values = list(values)
                    values[columns.index("review_state")] = "unreviewed"
                if table in LEGACY_COLUMNS and len(values) == len(LEGACY_COLUMNS[table]):
                    values = list(values) + [DEFAULTS[k] for k in columns[len(values):]]
                base = LEGACY_COLUMNS.get(table, columns)
                try:
                    placeholders = ",".join("?" for _ in base)
                    db.execute(f"INSERT INTO {table} ({','.join(base)}) VALUES ({placeholders})", values[:len(base)])
                    if table == "mode_value":
                        basis, applicability = values[len(base):]
                        db.execute("INSERT INTO mode_value_meta VALUES (?,?,?,?,?)",
                                   (values[0], values[1], basis or "stated", applicability, batch))
                except sqlite3.IntegrityError as error:
                    raise ValueError(f"{table} row {row}: {error}") from error
        # Values cited to an example source are synthetic whatever the file claims.
        db.execute("""UPDATE mode_value_meta SET value_basis='synthetic' WHERE value_basis<>'synthetic'
                      AND (mode_id, field) IN (SELECT mode_id, field FROM mode_value
                      WHERE source_id IN (SELECT id FROM source WHERE kind='example'))""")
        if issue := db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError(f"Unresolved record reference in {issue[0]}.")
        warnings = _validate_database(db)
        if apply:
            db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
                       ("equipment library", "import", actor.strip(), datetime.now(UTC).isoformat(),
                        str({k: len(v) for k, v in staged.items()})))
        else:
            db.execute(f"ROLLBACK TO {savepoint}")
    except BaseException:
        db.execute(f"ROLLBACK TO {savepoint}")
        raise
    finally:
        db.execute(f"RELEASE {savepoint}")
    return warnings


def export_exchange(db, path: Path):
    book = Workbook() if path.suffix.lower() == ".xlsx" else None
    if book:
        book.remove(book.active)
    else:
        path.mkdir(parents=True, exist_ok=True)
    for table, columns in TABLES.items():
        ordering = ", ".join(columns[:2] if table == "mode_value" else columns[:1])
        if table == "mode_value":
            rows = db.execute(f"""SELECT {', '.join('v.' + c for c in LEGACY_COLUMNS[table])},
                COALESCE(m.value_basis, 'stated'), m.applicability FROM mode_value v
                LEFT JOIN mode_value_meta m ON m.mode_id=v.mode_id AND m.field=v.field ORDER BY v.mode_id, v.field""")
        else:
            rows = db.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY {ordering}")
        if book:
            ws = book.create_sheet(table)
            ws.append(columns)
            for row in rows:
                ws.append(row)
                for cell in ws[ws.max_row]:
                    if isinstance(cell.value, str):
                        cell.data_type = "s"
        else:
            with (path / f"{table}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                # Prevent spreadsheet evaluation; read_exchange reverses this only
                # for strings emitted with the explicit escape marker.
                writer.writerows([_csv_encode(x) for x in row] for row in rows)
    if book:
        book.save(path)


_CSV_MARK = "~rammodel-text~"


def _csv_encode(value):
    if isinstance(value, str) and (
        value.startswith(_CSV_MARK) or value.lstrip().startswith(("=", "+", "-", "@")) or
        value.startswith(("\t", "\r", "\n"))
    ):
        return _CSV_MARK + value
    return value


def bind_library(db, model):
    """Populate selected graph assets from stored equipment, retaining field evidence."""
    from copy import deepcopy
    result = deepcopy(model)
    provenance = result.setdefault("provenance", {})
    mapping = {
        "logistics_hours": "logistics", "mobilisation_hours": "mobilisation",
        "active_repair_hours": "repair", "capacity_loss_fraction": "loss",
        "mtbf_hours": "mtbf", "weibull_shape": "shape", "weibull_scale_hours": "scale",
        "lognormal_sigma": "sigma", "lognormal_median_hours": "median", "proof_test_hours": "proof",
    }
    for asset in result["assets"]:
        if "equipment_id" not in asset:
            continue
        equipment = asset["equipment_id"]
        if not db.execute("SELECT 1 FROM equipment WHERE id=?", (equipment,)).fetchone():
            raise ValueError(f"Missing library equipment {equipment} for {asset['id']}.")
        prefix = f"modes/{asset['id']}/"
        for key in tuple(provenance):
            if key.startswith(prefix):
                del provenance[key]
        asset["modes"] = []
        for mode_id, detection, distribution, exposure in db.execute(
            "SELECT id,detection,distribution,exposure_basis FROM failure_mode WHERE equipment_id=? ORDER BY id",
            (equipment,),
        ):
            mode = {"id": mode_id, "distribution": distribution, "exposure": exposure, "detection": detection}
            evidence = {}
            for (field, value, citation, locator, original, unit, kind, uncertainty, low, high, factor,
                 basis, applicability, review, revision) in db.execute(
                """SELECT m.field,m.value,s.citation,m.source_locator,m.original_value,m.original_unit,
                   s.kind,m.uncertainty,m.low,m.high,m.error_factor,COALESCE(x.value_basis,'stated'),x.applicability,
                   m.review_state,s.revision FROM mode_value m
                   JOIN source s ON m.source_id=s.id
                   LEFT JOIN mode_value_meta x ON x.mode_id=m.mode_id AND x.field=m.field
                   WHERE m.mode_id=? ORDER BY m.field""", (mode_id,)
            ):
                if review == "rejected":
                    # A rejected value is retained in the library but never bound.
                    continue
                if field == "failure_rate_hour":
                    if value > 0 and "mtbf" not in mode:
                        mode["mtbf"] = 1 / value
                    elif value == 0:
                        raise ValueError(f"{mode_id}: zero failure rate needs an explicit no-failure model.")
                else:
                    mode[mapping[field]] = value
                evidence[field] = {"citation": citation, "locator": locator, "original": original, "units": unit,
                                   "kind": kind, "uncertainty": [uncertainty, low, high, factor],
                                   "basis": basis, "applicability": applicability, "review": review,
                                   "revision": revision}
                if kind == "example":
                    result["example"] = True
            if not evidence:
                raise ValueError(f"{mode_id}: no reliability evidence.")
            if (detection == "hidden") != ("proof" in mode) or detection == "unresolved":
                raise ValueError(f"{mode_id}: inconsistent or unresolved detection basis.")
            provenance[prefix + mode_id] = evidence
            asset["modes"].append(mode)
        if not asset["modes"] and not asset.get("explicit_no_failures"):
            raise ValueError(f"{equipment}: no failure modes. Supply inputs or explicitly approve no failures.")
    return result
