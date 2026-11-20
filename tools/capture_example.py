"""Capture screenshots from a live Qt window displaying the synthetic model."""
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))

from PySide6.QtWidgets import QApplication, QTabWidget
from rammodel.ui import Window

app = QApplication([])
app.setStyle("Fusion")
example = root / "examples" / "Offshore_Production"
window = Window(example / "Synthetic_Offshore.ramcase")
window.show()
app.processEvents()
for label, name in (("Production flow", "Production_Flow"), ("RBD path preview", "RBD_Path_Preview"),
                    ("Dependencies", "Utility_Dependencies")):
    window.view.setCurrentText(label)
    app.processEvents()
    if not window.grab().save(str(example / f"{name}.png")):
        raise RuntimeError(f"Could not save {name}")
window.tabs.setCurrentIndex(2)
inner = window.tabs.currentWidget().findChild(QTabWidget)
inner.setCurrentIndex(1)
app.processEvents()
if not window.grab().save(str(example / "Production_Results.png")):
    raise RuntimeError("Could not save production results")


def tab(title):
    for index in range(window.tabs.count()):
        if window.tabs.tabText(index) == title:
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            return
    raise RuntimeError(f"No tab {title}")


def save(folder, name):
    app.processEvents()
    if not window.grab().save(str(folder / f"{name}.png")):
        raise RuntimeError(f"Could not save {name}")


# 0.3 additions: model editor with a selected object, and a previewed decision study with its tornado.
window.tabs.setCurrentIndex(0)
window.view.setCurrentText("Production flow")
tab("Model editor")
window.editor.select("assets/COMP")
save(example, "Model_Editor")
from rammodel.decision import tornado
tab("Decisions")
window.preview_decisions()
spec, options, bars = window.decision_models()
window.show_decision({"kind": "tornado", "bars": tornado(window.model, bars, 42, 40),
                      "note": "Screenshot run: n=40 replications per bar, for illustration only."})
save(example, "Decisions_Tornado")
window.close()

onshore = root / "examples" / "Onshore_Utility_Reference"
window = Window(onshore / "Synthetic_Onshore.ramcase")
window.show()
for label, name in (("Production flow", "Onshore_Production_Flow"), ("Dependencies", "Onshore_Dependencies")):
    window.tabs.setCurrentIndex(0)
    window.view.setCurrentText(label)
    save(onshore, name)
print("Screenshots captured.")
