"""Desktop editing: shared selection, property form, connect, undo/redo, save/reopen, baseline guard."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rammodel.storage import open_case
from rammodel.study import digest


class DesktopEditing(unittest.TestCase):
    def test_edit_select_undo_save_reopen_and_baseline_guard(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QTableWidgetItem
        from rammodel.ui import Window

        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory(prefix="RAM & Desktop ü ") as folder:
            path = Path(folder) / "edit case.ramcase"
            window = Window()
            window.path = path
            window.show()
            app.processEvents()
            window.add_asset_dialog("SEP-X")
            window.add_edge_between("manifold", "tank", 30, key="train-X")
            self.assertIn("edges/train-X", [window.objects.item(i).text() for i in range(window.objects.count())])
            # Selection in the diagram drives the evidence panel, list and property form.
            window.picked("edges/train-X")
            self.assertEqual(window.objects.currentItem().text(), "edges/train-X")
            self.assertIn("train-X", window.evidence.toPlainText())
            rows = {window.props.item(r, 0).text(): r for r in range(window.props.rowCount())}
            window.props.setItem(rows["assets"], 1, QTableWidgetItem(json.dumps(["SEP-X"])))
            window.apply_properties()
            edge = next(e for e in window.model["edges"] if e["id"] == "train-X")
            self.assertEqual(edge["assets"], ["SEP-X"])
            window.undo_edit()
            self.assertEqual(next(e for e in window.model["edges"] if e["id"] == "train-X")["assets"], [])
            window.redo_edit()
            self.assertEqual(len(window.editor.change_list()), 5)
            self.assertIn("add_edge", window.changes_view.toPlainText())
            window.save_dialog()
            saved = digest(window.model)
            with open_case(path) as db:
                actions = [r[0] for r in db.execute("SELECT action FROM review_log")]
            self.assertGreaterEqual(actions.count("model edit"), 3)
            window.close()
            reopened = Window(path)
            self.assertEqual(digest(reopened.model), saved)
            # Approve, then try to edit: refusing the confirmation leaves the baseline untouched.
            reopened.model["unresolved"] = []
            with open_case(path) as db:
                db.execute("UPDATE study SET reviewer='Reviewer', reviewed_at='now' WHERE model_hash=?", (saved,))
            reopened.open_path(path)
            self.assertEqual(reopened.approved_hash, saved)
            reopened.editor.select("edges/train-X")
            self.assertFalse(reopened.edit({"op": "set", "target": ["edges", "train-X", "capacity"], "value": 35},
                                           confirm=lambda: False))
            self.assertEqual(digest(reopened.model), saved)
            self.assertTrue(reopened.edit({"op": "set", "target": ["edges", "train-X", "capacity"], "value": 35},
                                          confirm=lambda: True))
            self.assertNotEqual(digest(reopened.model), saved)
            self.assertNotIn("APPROVED BASELINE", reopened.model_label.text())
            reopened.close()


if __name__ == "__main__":
    unittest.main()
