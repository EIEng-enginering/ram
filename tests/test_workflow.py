from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rammodel.assistant import apply_proposal, validate_claims, validate_experiment
from rammodel.example import buffer_benchmark, offshore
from rammodel.exchange import bind_library, export_exchange, import_exchange, read_exchange
from rammodel.fixtures import equipment_fixture
from rammodel.reporting import approve_narrative, approve_run, export, metric_catalogue
from rammodel.storage import open_case
from rammodel.study import calculate, digest, review_model, save_model, save_run


class Workflows(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix="RAM & Approval ")
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def test_excel_csv_preview_roundtrip_and_binding(self):
        files = [self.folder / "Library.xlsx", self.folder / "Library CSV"]
        with open_case(self.folder / "source.ramcase") as db:
            fixture = equipment_fixture()
            fixture["source"][0][1][2] = '=EXAMPLE()'
            self.assertEqual(import_exchange(db, fixture, "test", apply=True), [])
            for path in files:
                export_exchange(db, path)
        for i, path in enumerate(files):
            with open_case(self.folder / f"destination_{i}.ramcase") as db:
                staged = read_exchange(path)
                self.assertEqual(import_exchange(db, staged, "test"), [])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source").fetchone()[0], 0)
                self.assertEqual(import_exchange(db, staged, "test", apply=True), [])
                self.assertEqual(db.execute("SELECT citation FROM source").fetchone()[0], "=EXAMPLE()")
                model = offshore()
                model["assets"][1]["equipment_id"] = "PWR-A"
                bound = bind_library(db, model)
                self.assertEqual(bound["assets"][1]["modes"][0]["mtbf"], 2100)
                self.assertTrue(bound["example"])

    def test_report_review_stale_and_formats(self):
        model = buffer_benchmark()
        with open_case(self.folder / "report.ramcase") as db:
            sha = save_model(db, model)
            run = calculate(model, seed=1, initial=2, maximum=2)
            save_run(db, run)
            claim = [{"text": "The modelled tank covers the test outage.", "metric": "shortfall"}]
            with self.assertRaises(ValueError):
                export(db, run["id"], self.folder, final=True)
            review_model(db, "Test reviewer", sha)
            with self.assertRaises(ValueError):
                export(db, run["id"], self.folder, claims=claim, final=True)
            approve_narrative(db, run["id"], claim, "Test reviewer")
            # 0.3: final export additionally requires a separate named run approval (WP5).
            with self.assertRaises(ValueError):
                export(db, run["id"], self.folder, claims=claim, final=True)
            approve_run(db, run["id"], "Run reviewer")
            stem = export(db, run["id"], self.folder, claims=claim, final=True)
            report_json = json.loads(stem.with_suffix(".json").read_text())
            self.assertIn("EXAMPLE DATA", report_json["status"])
            self.assertEqual(report_json["run"]["model_hash"], sha)
            for suffix in (".pdf", ".docx", ".xlsx"):
                self.assertGreater(stem.with_suffix(suffix).stat().st_size, 1000)
            edited = deepcopy(model)
            edited["buffer"]["initial"] = 200
            save_model(db, edited)
            with self.assertRaises(ValueError):
                export(db, run["id"], self.folder, final=True)
            stem = export(db, run["id"], self.folder)
            self.assertIn("STALE", json.loads(stem.with_suffix(".json").read_text())["status"])

    def test_ai_output_boundaries(self):
        model = offshore()
        before = digest(model)
        action = {"kind": "dependency", "item": {"asset": "SEP-A", "requires": "COMP"},
                  "source": "data", "reason": "Control narrative."}
        candidate = apply_proposal(model, [action], {"data": "Compression enables first train."})
        self.assertEqual(digest(model), before)
        self.assertIn("COMP", candidate["assets"][3]["requires"])
        self.assertTrue(candidate["unresolved"])
        with self.assertRaises(ValueError):
            apply_proposal(model, [action], {})
        with self.assertRaises(ValueError):
            validate_experiment({"action": "simulate", "seed": 1, "n": 999999, "buffer_capacity": None}, model)
        run = calculate(buffer_benchmark(), seed=42, initial=2, maximum=2)
        with self.assertRaises(ValueError):
            validate_claims([{"text": "The model has 20 percent loss.", "metric": "efficiency"}], metric_catalogue(run))

    def test_csv_failed_import_rolls_back(self):
        with open_case(self.folder / "case.ramcase") as db:
            data = equipment_fixture()
            data["equipment"][1][1][1] = "missing-subsystem"
            with self.assertRaises(ValueError):
                import_exchange(db, data, "test", apply=True)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source").fetchone()[0], 0)


class Desktop(unittest.TestCase):
    def test_offscreen_windows_and_linked_views(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from rammodel.ui import Window

        app = QApplication.instance() or QApplication([])
        window = Window()
        window.show()
        app.processEvents()
        for view in ("Production flow", "RBD path preview", "Dependencies"):
            window.view.setCurrentText(view)
            self.assertGreater(len(window.diagram.scene().items()), 0)
        window.inspect("edges/train-A")
        self.assertIn("synthetic offshore basis", window.evidence.toPlainText())
        window.close()
