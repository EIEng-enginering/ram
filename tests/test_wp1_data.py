"""WP1 acceptance: units, mapped import, provenance, migration and revisions.

Expected values are computed by hand from unit definitions (1 d = 24 h,
1 bbl = 0.158987294928 m3 exactly, 1 FPMH = 1e-6 /h) or with an independent
gamma-distribution formulation of the Poisson interval.
"""
import csv
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook
from scipy.stats import gamma

from rammodel import storage
from rammodel.exchange import bind_library, export_exchange, import_exchange, read_exchange
from rammodel.mapping import apply_mapping, preview
from rammodel.observations import add_observation, estimate_rate, review_observation
from rammodel.simulation import Simulator
from rammodel.storage import open_case
from rammodel.study import get_revision, get_run, library_hash, revisions, save_model
from rammodel.units import UnitError, convert, convert_exposure, to_canonical

FIXTURES = Path(__file__).parent / "fixtures"

HEADER = ["Tag", "Class", "Failure mode", "Detection", "Distribution", "Exposure", "MTBF", "MTBF unit",
          "MTTR", "Logistics", "Loss %", "Applicability"]


def mapping(**extra):
    return {"schema": "rammodel-mapping-1", "header_row": 1,
            "source": {"id": "VENDOR-1", "kind": "vendor", "citation": "Synthetic vendor table rev B", "revision": "B"},
            "subsystem": {"id": "process", "name": "Process"},
            "columns": {"tag": "Tag", "equipment_class": "Class", "mode": "Failure mode", "detection": "Detection",
                        "distribution": "Distribution", "exposure": "Exposure"},
            "values": [{"field": "mtbf_hours", "column": "MTBF", "unit_column": "MTBF unit"},
                       {"field": "active_repair_hours", "column": "MTTR", "unit": "h"},
                       {"field": "logistics_hours", "column": "Logistics", "unit": "d"},
                       {"field": "capacity_loss_fraction", "column": "Loss %", "unit": "%"}],
            "applicability": {"column": "Applicability"}, **extra}


class Units(unittest.TestCase):
    def test_conversions_by_definition(self):
        self.assertEqual(convert(2, "d", "h"), 48)
        self.assertAlmostEqual(convert(3, "per 1e6 h", "1/h"), 3e-6, places=18)
        self.assertAlmostEqual(convert(1000, "bbl/d", "m3/h"), 1000 * 0.158987294928 / 24, places=12)
        self.assertAlmostEqual(convert(1, "yr", "h"), 8760)
        self.assertAlmostEqual(to_canonical("50", "%", "fraction").value, 0.5)
        self.assertAlmostEqual(convert(1, "kg/s", "t/h"), 3.6)

    def test_cross_dimension_and_ambiguous_rejected(self):
        for args in ((1, "h", "m3"), (1, "m3/h", "Sm3/h"), (1, "1/h", "h")):
            with self.assertRaises(UnitError):
                convert(*args)
        with self.assertRaises(UnitError):
            to_canonical(100, "1/h", "time")
        for unit in ("month", "m"):
            with self.assertRaises(UnitError):
                to_canonical(1, unit)

    def test_blank_is_not_zero_and_original_kept(self):
        with self.assertRaises(UnitError):
            to_canonical("", "h", "time")
        with self.assertRaises(UnitError):
            to_canonical(None, "h", "time")
        zero = to_canonical("0", "h", "time")
        self.assertEqual((zero.value, zero.original_value, zero.original_unit), (0.0, "0", "h"))
        q = to_canonical(" 12.5 ", "days", "time")
        self.assertEqual((q.value, q.original_value, q.original_unit, q.unit), (300.0, "12.5", "days", "h"))

    def test_exposure_bases_never_mixed_implicitly(self):
        with self.assertRaises(UnitError):
            convert_exposure(1e-4, "operating", "calendar")
        self.assertAlmostEqual(convert_exposure(1e-4, "operating", "calendar", 0.5), 5e-5)
        self.assertAlmostEqual(convert_exposure(5e-5, "calendar", "operating", 0.5), 1e-4)


class MappedImport(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="RAM & Import ")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def write(self, rows, name="vendor.csv"):
        path = self.folder / name
        if path.suffix == ".csv":
            with path.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows([HEADER, *rows])
        else:
            book = Workbook()
            ws = book.active
            ws.title = "Data"
            for row in [HEADER, *rows]:
                ws.append(row)
            book.save(path)
        return path

    GOOD = [["P-101", "Pump", "Trip", "revealed", "exponential", "calendar", "100", "d", "8", "0", "100", "Seawater"],
            ["P-102", "Pump", "Trip", "revealed", "exponential", "calendar", "2400", "h", "", "1.5", "50", "Seawater"]]

    def test_preview_row_errors_mixed_units_blank_and_zero(self):
        rows = self.GOOD + [
            ["P-103", "Pump", "Trip", "revealed", "exponential", "calendar", "abc", "h", "8", "0", "100", ""],
            ["P-104", "Pump", "Trip", "revealed", "exponential", "calendar", "10", "m3", "8", "0", "100", ""],
            ["P-101", "Pump", "Trip", "revealed", "exponential", "calendar", "10", "h", "8", "0", "100", ""],
            ["P-105", "Pump", "Trip", "maybe", "exponential", "calendar", "10", "h", "8", "0", "100", ""]]
        result = preview(self.write(rows), mapping())
        errors = {(e["row"], e["cell"]): e["message"] for e in result["errors"]}
        self.assertIn((4, "G4"), errors)            # non-numeric MTBF
        self.assertIn("time", errors[(5, "G5")])    # m3 is not a duration
        self.assertIn("duplicate", errors[(6, "A6")])
        self.assertIn((7, "D7"), errors)            # invalid detection category
        self.assertTrue(any("mixed units for mtbf_hours" in w["message"] for w in result["warnings"]))
        status = {(r["row"], r["field"]): r["status"] for r in result["rows"]}
        self.assertEqual(status[(3, "active_repair_hours")], "missing")
        self.assertEqual(status[(2, "logistics_hours")], "zero")
        self.assertEqual(status[(2, "mtbf_hours")], "stated")
        with open_case(self.folder / "c.ramcase") as db:
            with self.assertRaises(ValueError):
                apply_mapping(db, result, "tester")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mode_value").fetchone()[0], 0)

    def test_apply_preserves_original_and_canonical_values(self):
        for name in ("vendor.csv", "vendor.xlsx"):
            extra = {"sheet": "Data"} if name.endswith("xlsx") else {}
            result = preview(self.write(self.GOOD, name), mapping(**extra))
            self.assertEqual(result["errors"], [])
            with open_case(self.folder / f"{name}.ramcase") as db:
                batch, _ = apply_mapping(db, result, "tester")
                got = {(m, f): (v, o, u) for m, f, v, o, u in db.execute(
                    "SELECT mode_id, field, value, original_value, original_unit FROM mode_value")}
                self.assertEqual(got[("P-101/Trip", "mtbf_hours")], (2400.0, "100", "d"))
                self.assertEqual(got[("P-102/Trip", "mtbf_hours")], (2400.0, "2400", "h"))
                self.assertEqual(got[("P-102/Trip", "logistics_hours")], (36.0, "1.5", "d"))
                self.assertEqual(got[("P-101/Trip", "logistics_hours")][0], 0.0)
                self.assertEqual(got[("P-102/Trip", "capacity_loss_fraction")][0], 0.5)
                self.assertNotIn(("P-102/Trip", "active_repair_hours"), got)  # blank stays missing
                locator = db.execute("SELECT source_locator FROM mode_value WHERE mode_id='P-101/Trip' "
                                     "AND field='mtbf_hours'").fetchone()[0]
                self.assertTrue(locator.endswith("G2"))
                meta = db.execute("SELECT value_basis, applicability, import_batch FROM mode_value_meta "
                                  "WHERE mode_id='P-101/Trip' AND field='mtbf_hours'").fetchone()
                self.assertEqual(meta, ("stated", "Seawater", batch))
                self.assertEqual(db.execute("SELECT row_count FROM import_batch").fetchone()[0], 7)

    def test_failed_batch_rolls_back_everything(self):
        result = preview(self.write(self.GOOD), mapping())
        with open_case(self.folder / "c.ramcase") as db:
            db.execute("INSERT INTO subsystem VALUES ('process', NULL, 'Process')")
            before = library_hash(db)
            with self.assertRaises(ValueError):
                apply_mapping(db, result, "tester")   # subsystem row conflicts mid-batch
            self.assertEqual(library_hash(db), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 0)

    def test_exchange_round_trip_reproduces_inputs(self):
        result = preview(self.write(self.GOOD), mapping())
        with open_case(self.folder / "a.ramcase") as db:
            apply_mapping(db, result, "tester")
            original = sorted(db.execute("""SELECT v.*, m.value_basis, m.applicability FROM mode_value v
                JOIN mode_value_meta m USING (mode_id, field)""").fetchall())
            export_exchange(db, self.folder / "out.xlsx")
            export_exchange(db, self.folder / "out_csv")
        for path in (self.folder / "out.xlsx", self.folder / "out_csv"):
            with open_case(self.folder / f"b_{path.stem}.ramcase") as db:
                import_exchange(db, read_exchange(path), "tester", apply=True)
                again = sorted(db.execute("""SELECT v.*, m.value_basis, m.applicability FROM mode_value v
                    JOIN mode_value_meta m USING (mode_id, field)""").fetchall())
                self.assertEqual(again, original)

    def test_legacy_alpha_exchange_files_import(self):
        with open_case(self.folder / "legacy.ramcase") as db:
            import_exchange(db, read_exchange(FIXTURES / "alpha_0_2_exchange_csv"), "tester", apply=True)
            n = db.execute("SELECT COUNT(*) FROM mode_value").fetchone()[0]
            self.assertEqual(n, 35)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mode_value_meta WHERE value_basis='synthetic'"
                                        ).fetchone()[0], n)

    def test_bind_skips_rejected_and_carries_basis(self):
        result = preview(self.write(self.GOOD), mapping())
        with open_case(self.folder / "c.ramcase") as db:
            apply_mapping(db, result, "tester")
            db.execute("UPDATE mode_value SET review_state='rejected' WHERE mode_id='P-101/Trip' AND field='mtbf_hours'")
            model = {"assets": [{"id": "P-101", "equipment_id": "P-101", "modes": []}], "provenance": {}}
            bound = bind_library(db, model)
            mode = bound["assets"][0]["modes"][0]
            self.assertNotIn("mtbf", mode)
            evidence = bound["provenance"]["modes/P-101/P-101/Trip"]
            self.assertEqual(evidence["active_repair_hours"]["basis"], "stated")
            self.assertEqual(evidence["active_repair_hours"]["revision"], "B")


class CaseIntegrity(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="RAM & Migrate ")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_migrate_alpha_case_copy_without_losing_run(self):
        alpha = FIXTURES / "alpha_0_2_Synthetic_Offshore.ramcase"
        path = self.folder / "alpha copy ü.ramcase"
        shutil.copyfile(alpha, path)
        raw = sqlite3.connect(path)
        before_runs = raw.execute("SELECT id, model_hash, record_json FROM run").fetchall()
        before_model = raw.execute("SELECT model_json, model_hash FROM study").fetchone()
        self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 2)
        raw.close()
        with open_case(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], storage.SCHEMA_VERSION)
            self.assertEqual(db.execute("SELECT id, model_hash, record_json FROM run").fetchall(), before_runs)
            self.assertEqual(db.execute("SELECT model_json, model_hash FROM study").fetchone(), before_model)
            self.assertEqual([r["hash"] for r in revisions(db)], [before_model[1]])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mode_value_meta WHERE value_basis='synthetic'"
                                        ).fetchone()[0], 35)
            record = get_run(db, before_runs[0][0])
        # The stored alpha run is reproducible from its own snapshot and seed.
        replay = Simulator(record["model"]).replay(record["result"]["seed"], 0, True)
        stored = record["result"]["preview"]
        self.assertEqual(len(replay["intervals"]), len(stored["intervals"]))
        self.assertAlmostEqual(replay["efficiency"], stored["efficiency"], places=12)
        self.assertEqual(json.loads(json.dumps(replay["loss_groups"])).keys(), stored["loss_groups"].keys())

    def test_revision_history_and_reopen(self):
        path = self.folder / "rev.ramcase"
        a = {"name": "A", "assets": [], "edges": []}
        b = {"name": "B", "assets": [], "edges": []}
        with open_case(path) as db:
            ha = save_model(db, a, "Engineer One", "first")
            hb = save_model(db, b, "Engineer Two", "second")
        with open_case(path) as db:
            history = revisions(db)
            self.assertEqual([h["hash"] for h in history], [ha, hb])
            self.assertEqual(history[1]["parent_hash"], ha)
            self.assertEqual(get_revision(db, ha), a)

    def test_rate_estimate_from_accepted_observations_only(self):
        with open_case(self.folder / "obs.ramcase") as db:
            db.execute("INSERT INTO source VALUES ('SITE', 'site', 'Synthetic maintenance log', NULL, '1')")
            db.execute("INSERT INTO subsystem VALUES ('s', NULL, 'S')")
            db.execute("INSERT INTO equipment VALUES ('P', 's', 'P', 'Pump')")
            db.execute("INSERT INTO failure_mode VALUES ('P/trip', 'P', 'Trip', 'revealed', 'exponential', 'operating')")
            add_observation(db, "o1", "P/trip", 3, 12000, "operating", "SITE", "log 2024")
            add_observation(db, "o2", "P/trip", 1, 8000, "operating", "SITE", "log 2025")
            with self.assertRaises(ValueError):
                estimate_rate(db, "P/trip", "tester")       # unreviewed
            review_observation(db, "o1", "Reviewer")
            review_observation(db, "o2", "Reviewer")
            estimate = estimate_rate(db, "P/trip", "tester")
            self.assertAlmostEqual(estimate["rate_per_h"], 4 / 20000)
            # Independent: Poisson exact interval via gamma quantiles.
            self.assertAlmostEqual(estimate["interval_per_h"][0], gamma.ppf(.025, 4) / 20000, places=12)
            self.assertAlmostEqual(estimate["interval_per_h"][1], gamma.ppf(.975, 5) / 20000, places=12)
            row = db.execute("""SELECT v.uncertainty, m.value_basis FROM mode_value v JOIN mode_value_meta m
                                USING (mode_id, field) WHERE field='failure_rate_hour'""").fetchone()
            self.assertEqual(row, ("bounds", "estimated"))
            add_observation(db, "o3", "P/trip", 1, 100, "calendar", "SITE", "log 2026")
            review_observation(db, "o3", "Reviewer")
            with self.assertRaises(ValueError):
                estimate_rate(db, "P/trip", "tester")       # mixed exposure basis


if __name__ == "__main__":
    unittest.main()
