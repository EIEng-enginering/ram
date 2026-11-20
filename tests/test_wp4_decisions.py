"""WP4: paired option decisions, validity notes, rank resolution, input-uncertainty
ranking changes, tornado ordering and separation of uncertainty kinds."""
from copy import deepcopy
import unittest

from rammodel.decision import compare_options, comparison_validity, model_diff, ranking_under_uncertainty, tornado
from rammodel.study import paired_compare


def model(x_mtbf=200.0, x_repair=20.0, y_repair=20.0):
    def a(key, mtbf, repair):
        return {"id": key, "modes": [{"id": "trip", "distribution": "exponential", "mtbf": mtbf, "loss": 1.0,
                                      "logistics": 0.0, "mobilisation": 0.0, "repair": repair}]}
    return {"name": "decision", "source": "in", "sink": "out", "target": 100, "hours": 2000, "volume_unit": "m3",
            "assets": [a("X", x_mtbf, x_repair), a("Y", 200.0, y_repair)],
            "edges": [{"id": "x", "from": "in", "to": "m", "capacity": 100, "assets": ["X"]},
                      {"id": "y", "from": "m", "to": "out", "capacity": 100, "assets": ["Y"]}],
            "provenance": {"modes/X/trip": "EXAMPLE", "modes/Y/trip": "EXAMPLE"}}


class Decisions(unittest.TestCase):
    def test_insignificant_difference_is_reported_as_unresolved(self):
        base = model()
        # Same parameters on a renamed (unmatched) stream: the true difference is zero, sampling noise remains.
        tiny = model()
        tiny["assets"][0]["modes"][0]["id"] = "trip-renamed"
        result = compare_options(base, {"tiny": tiny, "big": model(x_mtbf=400)}, seed=3, n=60)
        by = {o["option"]: o for o in result["options"]}
        self.assertFalse(by["tiny"]["difference"]["significant"])
        self.assertIn("no resolved difference", by["tiny"]["interpretation"])
        self.assertTrue(by["big"]["difference"]["significant"])
        self.assertEqual(by["big"]["changes"], ["changed assets[X]/modes[trip]/mtbf: 200.0 -> 400"])
        self.assertTrue(any("unmatched" in n for n in by["tiny"]["validity"]["notes"]))
        # Matched streams resolve even a small real change (20 -> 20.05 h repair): consistent sign in every pair.
        small = compare_options(base, {"small": model(x_repair=20.05)}, seed=3, n=60)["options"][0]
        self.assertTrue(small["difference"]["significant"])
        self.assertLess(small["difference"]["mean"], 0)
        self.assertEqual(result["ranking"][0], "big")
        compared = paired_compare(base, tiny, 3, 60)
        self.assertEqual(compared["difference"]["kind"], "paired_delta")
        self.assertEqual(compared["base"]["kind"], "sampling")

    def test_indistinguishable_adjacent_options_flagged(self):
        result = compare_options(model(), {"a": model(x_repair=19.9), "b": model(y_repair=19.9)}, seed=4, n=40)
        self.assertFalse(result["adjacent"][0]["distinguishable"])

    def test_validity_notes_for_changed_logic(self):
        base = model()
        rerouted = deepcopy(base)
        rerouted["edges"].append({"id": "bypass", "from": "in", "to": "m", "capacity": 50, "assets": []})
        notes = comparison_validity(base, rerouted)["notes"]
        self.assertTrue(any("Routing" in n for n in notes))
        self.assertEqual(comparison_validity(base, model(x_repair=10))["matched_stream_fraction"], 1.0)
        self.assertTrue(any("added edges[bypass]" in c for c in model_diff(base, rerouted)))

    def test_ranking_changes_under_credible_input_uncertainty(self):
        # Fix X (halve X repair) gains about 10/MTBF_X; fix Y gains about 10/200. Fix X wins when
        # MTBF_X < 200 h: probability (200-50)/(500-50) = 1/3 for MTBF_X ~ U[50, 500].
        options = {"fix X": model(x_repair=10), "fix Y": model(y_repair=10)}
        result = ranking_under_uncertainty(options, [("X", "trip", "mtbf", 50, 500)], seed=8, outer=24, inner=30)
        self.assertEqual(result["kind"], "input")
        self.assertGreater(result["ranking_changes"], 0)
        self.assertLess(result["ranking_changes"], 1)
        self.assertGreater(result["probability_best"]["fix X"], 0)
        self.assertGreater(result["probability_best"]["fix Y"], 0)

    def test_tornado_sorted_by_swing_with_source_links(self):
        base = model()
        bars = tornado(base, [("Y repair", "modes/Y/trip", model(y_repair=15), model(y_repair=25)),
                              ("X repair", "modes/X/trip", model(x_repair=5), model(x_repair=60))], seed=2, n=40)
        self.assertEqual([b["input"] for b in bars], ["X repair", "Y repair"])
        self.assertEqual(bars[0]["source"], "modes/X/trip")
        self.assertGreater(bars[0]["low"], 0)
        self.assertLess(bars[0]["high"], 0)


if __name__ == "__main__":
    unittest.main()


class DecisionDesktop(unittest.TestCase):
    def test_preview_required_then_compare_in_desktop(self):
        import json
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from rammodel.ui import Window
        app = QApplication.instance() or QApplication([])
        window = Window()
        spec = json.loads(window.decision_spec.toPlainText())
        spec["n"] = 20
        window.decision_spec.setPlainText(json.dumps(spec))
        with self.assertRaises(ValueError):
            window.run_decisions("compare", confirmed=True)
        window.preview_decisions()
        self.assertIn("changed buffer/capacity: 600 -> 1200", window.decision_text.toPlainText())
        window.run_decisions("compare", confirmed=True)
        window.worker.wait()
        app.processEvents()
        self.assertEqual(window.last_decision["ranking"], ["Doubled tank"])
        window.run_decisions("tornado", confirmed=True)
        window.worker.wait()
        app.processEvents()
        self.assertEqual(window.last_decision["bars"][0]["source"], "modes/EXP-A/trip")
        self.assertFalse(window.tornado_view.pixmap().isNull())
        window.close()
