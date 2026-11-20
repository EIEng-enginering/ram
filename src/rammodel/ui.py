"""PySide6 desktop workspace for the first end-to-end RAM workflow."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .assistant import apply_proposal, draft_claims, plan_experiment, propose, validate_experiment
from .example import offshore_extended
from .decision import compare_options, model_diff, ranking_under_uncertainty, render_tornado, tornado
from .editing import BaselineChangeError, ModelEditor, _apply as apply_command
from .engineering_import import import_topology
from .exchange import bind_library, export_exchange, import_exchange, read_exchange
from .reporting import _plot, approve_narrative, approve_run, export, metric_catalogue
from .simulation import Simulator
from .storage import open_case
from .study import calculate, current_model, digest, get_run, paired_compare, review_model, save_model, save_run


class Job(QThread):
    done = Signal(object)
    error = Signal(str)
    update = Signal(int)

    def __init__(self, task, parent):
        super().__init__(parent)
        self.task = task
        self.cancel = Event()

    def run(self):
        try:
            self.done.emit(self.task(self.update.emit, self.cancel))
        except Exception as error:
            self.error.emit(str(error))


class Diagram(QGraphicsView):
    picked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#eef3f6"))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(0):
            self.picked.emit(item.data(0))
        super().mousePressEvent(event)

    def highlight(self, key):
        """Show the shared selection in this view."""
        for item in self.scene().items():
            if hasattr(item, "setPen") and not hasattr(item, "text"):
                selected = key is not None and item.data(0) == key
                pen = item.pen()
                pen.setColor(QColor("#d4581c" if selected else ("#427488" if item.type() == 6 else "#16495c")))
                pen.setWidthF(4.0 if selected else (2.5 if item.type() == 6 else 1.0))
                item.setPen(pen)

    def draw(self, model, view):
        scene = self.scene()
        scene.clear()
        nodes, links = {}, []
        if view == "Production flow":
            for e in model["edges"]:
                links.append((e["from"], e["to"], f"{e['id']} · {e['capacity']}", f"edges/{e['id']}"))
                nodes.update({e["from"]: e["from"], e["to"]: e["to"]})
        elif view == "Dependencies":
            for a in model["assets"]:
                nodes[a["id"]] = a["id"]
                for parent in a.get("requires", []):
                    links.append((parent, a["id"], "requires", f"dependencies/{a['id']}/{parent}"))
        else:
            for e in model["edges"]:
                nodes[e["from"]], nodes[e["to"]] = e["from"], e["to"]
                stage = f"edge:{e['id']}"
                nodes[stage] = " ∧ ".join(e.get("assets", [])) or "Flow path"
                links += [(e["from"], stage, "", f"edges/{e['id']}"), (stage, e["to"], "", f"edges/{e['id']}")]
        depth = dict.fromkeys(nodes, 0)
        for _ in nodes:
            changed = False
            for a, b, _, _ in links:
                if a in depth and b in depth and depth[b] <= depth[a]:
                    depth[b] = min(len(nodes) - 1, depth[a] + 1)
                    changed = True
            if not changed:
                break
        columns = defaultdict(list)
        for item in nodes:
            columns[depth[item] if view != "Dependencies" or depth[item] else len(columns[0]) // 4].append(item)
        positions = {node: (215 * d, 100 * (i - (len(members) - 1) / 2))
                     for d, members in columns.items() for i, node in enumerate(members)}
        for a, b, label, key in links:
            if a not in positions or b not in positions:
                continue
            x, y = positions[a]
            xx, yy = positions[b]
            link = scene.addLine(x + 150, y + 22, xx, yy + 22, QPen(QColor("#427488"), 2.5))
            link.setData(0, key)
            if label:
                text = scene.addSimpleText(label, QFont("Segoe UI", 8))
                text.setPos((x + 150 + xx) / 2 - 22, (y + yy) / 2 - 2)
                text.setData(0, key)
        for node, label in nodes.items():
            x, y = positions[node]
            item = scene.addRect(x, y, 150, 44, QPen(QColor("#16495c")), QColor("#ffffff"))
            key = (f"edges/{node[5:]}" if node.startswith("edge:") else f"assets/{node}"
                   if view == "Dependencies" else f"nodes/{node}")
            item.setData(0, key)
            title = scene.addSimpleText(label[:25], QFont("Segoe UI", 10))
            title.setPos(x + 8, y + 11)
            title.setData(0, key)
        self.resetTransform()
        bounds = scene.itemsBoundingRect().adjusted(-30, -20, 30, 20)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)


class Window(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.setWindowTitle("RAM Model | Enhance Integration Engineering")
        self.resize(1250, 780)
        self.path, self.run_id, self.pending, self.worker = None, None, None, None
        self.claims = []
        self.model = offshore_extended()
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.statusBar().showMessage("Synthetic example loaded • save as a RAM case to begin")
        self.model_editor = QPlainTextEdit()
        self.evidence = QPlainTextEdit(readOnly=True)
        self.diagram = Diagram()
        self.diagram.picked.connect(self.picked)
        self.editor = ModelEditor(self.model, validator=Simulator)
        self.editor.listeners.append(self.on_select)
        self.approved_hash = None
        self.connect_from = None
        self.view = QComboBox()
        self.view.addItems(["Production flow", "RBD path preview", "Dependencies"])
        self.view.currentTextChanged.connect(lambda _: self.render())
        self.model_label = QLabel()
        self.model_label.setWordWrap(True)
        panel = self.panel("Model", self.model_label,
                           self.buttons(("Open case", self.open_dialog), ("Save case", self.save_dialog),
                                        ("Load model JSON", self.load_json), ("Synthetic offshore", self.load_example),
                                        ("Apply JSON edits", self.apply_edits), ("Approve revision", self.review)), self.view)
        upper = QSplitter()
        upper.addWidget(self.diagram)
        upper.addWidget(self.evidence)
        upper.setSizes([850, 350])
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(upper)
        split.addWidget(self.model_editor)
        split.setSizes([540, 160])
        panel.addWidget(split)
        self.import_text = QPlainTextEdit(readOnly=True)
        self.panel("Inputs", QLabel("Preview and apply the equipment library, then bind graph assets by equipment_id."),
                   self.buttons(("Preview XLSX", lambda: self.stage(False)), ("Preview CSV directory", lambda: self.stage(True)),
                                ("Apply staged library", self.apply_library), ("Export XLSX", self.export_library),
                                ("Bind library to model", self.bind)), self.import_text)
        self.controls = QHBoxLayout()
        self.seed, self.initial, self.maximum = (QSpinBox() for _ in range(3))
        for name, value, maximum, box in (("Seed", 42, 2147483647, self.seed),
                                           ("Initial runs", 1000, 100000, self.initial),
                                           ("Maximum runs", 100000, 100000, self.maximum)):
            box.setRange(2 if box is not self.seed else 0, maximum)
            box.setValue(value)
            self.controls.addWidget(QLabel(name))
            self.controls.addWidget(box)
        self.controls.addStretch()
        self.result_text = QPlainTextEdit(readOnly=True)
        self.chart = QLabel("Run a study to view the production and storage profile")
        self.chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeline = QTableWidget(0, 6)
        self.timeline.setHorizontalHeaderLabels(["Start h", "End h", "Delivery rate", "Buffer at end", "Shortfall", "Outage group"])
        result_panel = self.panel("Results", self.buttons(("Run simulation", self.run),
                                                          ("Cancel run", self.cancel),
                                                          ("Load stored run", self.load_run),
                                                          ("Compare larger tank", self.compare)))
        result_details = QTabWidget()
        result_details.addTab(self.result_text, "Metrics")
        result_details.addTab(self.chart, "Production & storage")
        result_details.addTab(self.timeline, "Outage timeline")
        result_panel.addWidget(result_details, 1)
        result_panel.insertLayout(0, self.controls)
        self.provider = QComboBox()
        self.provider.addItems(["off", "local", "cloud"])
        self.provider_model = QPlainTextEdit()
        self.provider_model.setPlaceholderText("Provider model ID")
        self.provider_model.setMaximumHeight(38)
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Engineering question or modelling instruction")
        self.question.setMaximumHeight(65)
        self.excerpt = QPlainTextEdit()
        self.excerpt.setPlaceholderText("Paste only the evidence excerpt approved for this request.")
        self.excerpt.setMaximumHeight(115)
        self.ai_result = QPlainTextEdit()
        self.share = QCheckBox("I approve sending the displayed excerpt or run metrics to the configured cloud provider")
        self.panel("AI workspace", self.provider, self.provider_model, self.question, self.excerpt, self.share,
                   self.buttons(("Extract document (local)", self.extract_document), ("Use excerpt ID", self.use_excerpt)),
                   self.buttons(("Propose model", self.ai_model), ("Apply as draft", self.ai_apply),
                                ("Plan experiment", self.ai_plan), ("Run approved plan", self.ai_execute),
                                ("Draft narrative", self.ai_narrative)), self.ai_result)
        self.final = QCheckBox("Final engineer-reviewed export")
        self.panel("Reports", QLabel("Export the current run in Excel, Word, PDF and JSON."), self.final,
                   self.buttons(("Approve current run", self.run_approval), ("Approve AI narrative", self.narrative_approval),
                                ("Export reports", self.report)), QLabel("Outputs include basis, evidence, run statistics and a production/storage chart."))
        self.objects = QListWidget()
        self.objects.currentTextChanged.connect(lambda text: text and self.editor.selection != text and self.editor.select(text))
        self.props = QTableWidget(0, 2)
        self.props.setHorizontalHeaderLabels(["Property", "Value (JSON)"])
        self.props.horizontalHeader().setStretchLastSection(True)
        self.changes_view = QPlainTextEdit(readOnly=True)
        self.issue_label = QLabel()
        self.issue_label.setWordWrap(True)
        self.connect_mode = QCheckBox("Connect mode: click two nodes in the Production flow view to add a flow edge")
        edit_split = QSplitter()
        edit_split.addWidget(self.objects)
        edit_split.addWidget(self.props)
        edit_split.setSizes([300, 700])
        self.panel("Model editor", QLabel("Select an object here or in any diagram. Edit properties, connect nodes, "
                                          "undo or redo, then save the reviewed change list as a new revision."),
                   self.buttons(("Add asset", self.add_asset_dialog), ("Add edge", self.add_edge_dialog),
                                ("Apply properties", self.apply_properties), ("Delete selected", self.delete_selected),
                                ("Undo", self.undo_edit), ("Redo", self.redo_edit), ("Save edits", self.save_dialog)),
                   self.connect_mode, edit_split, self.issue_label, QLabel("Change list (unsaved)"), self.changes_view)
        self.decision_spec = QPlainTextEdit()
        self.decision_spec.setPlainText(json.dumps({
            "seed": 42, "n": 200,
            "options": {"Doubled tank": [{"op": "set_buffer", "id": "buffer", "value": {
                "node": "tank", "capacity": 1200, "initial": 600, "fill": 10, "draw": 100}}]},
            "tornado": [{"label": "Export pump MTBF", "source": "modes/EXP-A/trip",
                         "low": [{"op": "set", "target": ["assets", "EXP-A", "modes"], "value": [
                             {"id": "trip", "distribution": "exponential", "mtbf": 950, "loss": 1.0, "logistics": 2.0,
                              "mobilisation": 3.0, "repair": 14, "spare": "export"}]}],
                         "high": [{"op": "set", "target": ["assets", "EXP-A", "modes"], "value": [
                             {"id": "trip", "distribution": "exponential", "mtbf": 3800, "loss": 1.0, "logistics": 2.0,
                              "mobilisation": 3.0, "repair": 14, "spare": "export"}]}]}],
            "uncertainty": [["SEP-A", "trip", "mtbf", 900, 1600]]}, indent=2))
        self.decision_text = QPlainTextEdit(readOnly=True)
        self.tornado_view = QLabel("Tornado chart appears here")
        self.tornado_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decision_preview = None
        decision_split = QSplitter()
        decision_split.addWidget(self.decision_text)
        decision_split.addWidget(self.tornado_view)
        self.panel("Decisions", QLabel("Options are lists of editor commands applied to the current model. Preview the "
                                       "candidate changes, then approve to run paired comparisons, the tornado or the "
                                       "input-uncertainty ranking. Uncertainty kinds are labelled in every result."),
                   self.decision_spec,
                   self.buttons(("Preview candidate changes", self.preview_decisions),
                                ("Approve and compare options", lambda: self.run_decisions("compare")),
                                ("Approve and run tornado", lambda: self.run_decisions("tornado")),
                                ("Approve and rank under input uncertainty", lambda: self.run_decisions("uncertainty"))),
                   decision_split)
        self.render(True)
        if path:
            self.open_path(path)

    def panel(self, title, *widgets):
        page, layout = QWidget(), QVBoxLayout()
        page.setLayout(layout)
        for widget in widgets:
            layout.addWidget(widget)
        self.tabs.addTab(page, title)
        return layout

    def buttons(self, *items):
        row, layout = QWidget(), QHBoxLayout()
        row.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        for name, callback in items:
            button = QPushButton(name)
            button.clicked.connect(lambda _, action=callback: self.guard(action))
            layout.addWidget(button)
        layout.addStretch()
        return row

    def guard(self, action):
        try:
            action()
        except Exception as error:
            QMessageBox.warning(self, "RAM Model", str(error))

    def launch(self, label, task, done):
        if self.worker and self.worker.isRunning():
            raise ValueError("A background job is already running.")
        self.statusBar().showMessage(label)
        self.worker = Job(task, self)
        self.worker.update.connect(lambda count: self.statusBar().showMessage(f"{label} · {count:,} replications"))
        self.worker.done.connect(lambda value: self.guard(lambda: done(value)))
        self.worker.error.connect(lambda msg: self.statusBar().showMessage(msg))
        self.worker.start()

    def render(self, editor=False):
        if editor:
            self.model_editor.setPlainText(json.dumps(self.model, indent=2, ensure_ascii=False))
        self.diagram.draw(self.model, self.view.currentText())
        status = "EXAMPLE DATA" if self.model.get("example") else "Project data"
        approved = " • APPROVED BASELINE" if self.approved_hash == digest(self.model) else ""
        self.model_label.setText(f"{self.model.get('name', 'RAM model')}  •  {status}  •  Revision {digest(self.model)[:12]}{approved}  •  {len(self.model.get('unresolved', []))} unresolved items")
        if hasattr(self, "objects"):
            self.refresh_editor()

    # ---------------------------------------------------------------- editing
    def picked(self, key):
        if self.connect_mode.isChecked() and key.startswith("nodes/"):
            if self.connect_from is None:
                self.connect_from = key[6:]
                self.statusBar().showMessage(f"Connect from {self.connect_from}: pick the destination node")
                return
            start, self.connect_from = self.connect_from, None
            self.guard(lambda: self.add_edge_between(start, key[6:]))
            return
        self.editor.select(key)

    def on_select(self, key):
        self.inspect(key)
        self.diagram.highlight(key)
        items = self.objects.findItems(key, Qt.MatchFlag.MatchExactly)
        if items:
            self.objects.setCurrentItem(items[0])
        kind, _, item = key.partition("/")
        obj = next((x for x in self.model.get(kind, []) if x.get("id") == item), None) if kind in ("assets", "edges") else None
        rows = [(k, v) for k, v in (obj or {}).items() if k != "id"]
        self.props.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            name = QTableWidgetItem(k)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.props.setItem(i, 0, name)
            self.props.setItem(i, 1, QTableWidgetItem(json.dumps(v, ensure_ascii=False)))

    def confirm_baseline(self):
        return QMessageBox.question(self, "Approved baseline", "This edit changes the approved baseline and "
                                    "creates a new unapproved revision. Continue?") == QMessageBox.StandardButton.Yes

    def edit(self, command, confirm=None):
        try:
            self.editor.apply(command, "desktop user")
        except BaselineChangeError:
            if not (confirm or self.confirm_baseline)():
                return False
            self.editor.apply(command, "desktop user", confirm_baseline=True)
        self.model = self.editor.model
        self.render(True)
        return True

    def refresh_editor(self):
        keys = [f"assets/{a['id']}" for a in self.model.get("assets", [])] + [
            f"edges/{e['id']}" for e in self.model.get("edges", [])]
        self.objects.blockSignals(True)
        self.objects.clear()
        self.objects.addItems(keys)
        self.objects.blockSignals(False)
        self.changes_view.setPlainText("\n".join(self.editor.change_list()) or "No unsaved edits")
        issues = self.editor.issues()
        self.issue_label.setText("Engine check: " + ("; ".join(issues) if issues else "model runs in the supported profile"))
        if self.editor.selection:
            self.on_select(self.editor.selection)

    def add_asset_dialog(self, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Add asset", "Asset ID")
            if not ok:
                return
        self.edit({"op": "add_asset", "id": name.strip(), "explicit_no_failures": True})
        self.editor.select(f"assets/{name.strip()}")

    def add_edge_between(self, start, end, capacity=None, key=None):
        if capacity is None:
            capacity, ok = QInputDialog.getDouble(self, "Add flow edge", f"Capacity {start} → {end}", 100, 0, 1e12, 3)
            if not ok:
                return
        key = key or f"{start}-{end}"
        self.edit({"op": "add_edge", "id": key, "from": start, "to": end, "capacity": capacity, "assets": []})
        self.editor.select(f"edges/{key}")

    def add_edge_dialog(self):
        text, ok = QInputDialog.getText(self, "Add flow edge", "from,to,capacity")
        if ok:
            start, end, capacity = (x.strip() for x in text.split(","))
            self.add_edge_between(start, end, float(capacity))

    def apply_properties(self, confirm=None):
        key = self.editor.selection
        kind, _, item = (key or "").partition("/")
        if kind not in ("assets", "edges"):
            raise ValueError("Select an asset or edge first.")
        current = next(x for x in self.model[kind] if x["id"] == item)
        for row in range(self.props.rowCount()):
            field = self.props.item(row, 0).text()
            value = json.loads(self.props.item(row, 1).text())
            if current.get(field) != value:
                if not self.edit({"op": "set", "target": [kind, item, field], "value": value}, confirm):
                    return

    def delete_selected(self):
        kind, _, item = (self.editor.selection or "").partition("/")
        if kind == "assets":
            self.edit({"op": "remove_asset", "id": item})
        elif kind == "edges":
            self.edit({"op": "remove_edge", "id": item})
        else:
            raise ValueError("Select an asset or edge to delete.")
        self.editor.selection = None

    def undo_edit(self):
        self.model = self.editor.undo("desktop user")
        self.render(True)

    def redo_edit(self):
        self.model = self.editor.redo("desktop user")
        self.render(True)

    # ---------------------------------------------------------------- decisions
    def decision_models(self):
        spec = json.loads(self.decision_spec.toPlainText())

        def build(commands):
            model = deepcopy(self.model)
            for command in commands:
                model = apply_command(model, command)
            return model

        options = {name: build(cmds) for name, cmds in spec.get("options", {}).items()}
        bars = [(t["label"], t["source"], build(t["low"]), build(t["high"])) for t in spec.get("tornado", [])]
        return spec, options, bars

    def preview_decisions(self):
        spec, options, bars = self.decision_models()
        lines = []
        for name, option in options.items():
            lines += [f"Option {name}:"] + [f"  {c}" for c in model_diff(self.model, option)]
        for label, source, low, high in bars:
            lines += [f"Tornado {label} [{source}] low:"] + [f"  {c}" for c in model_diff(self.model, low)]
            lines += [f"Tornado {label} high:"] + [f"  {c}" for c in model_diff(self.model, high)]
        self.decision_preview = (digest(self.model), digest(spec))
        self.decision_text.setPlainText("CANDIDATE CHANGES (not applied to the baseline)\n" + "\n".join(lines))

    def run_decisions(self, kind, confirmed=False):
        spec, options, bars = self.decision_models()
        if self.decision_preview != (digest(self.model), digest(spec)):
            raise ValueError("Preview the candidate changes for the current model and specification first.")
        if not confirmed and QMessageBox.question(self, "Approve experiment", f"Run the {kind} study shown in the "
                                                  "preview?") != QMessageBox.StandardButton.Yes:
            return
        base, seed, n = deepcopy(self.model), spec.get("seed", 42), spec.get("n", 200)
        if kind == "compare":
            task = lambda p, c: compare_options(base, options, seed, n)
        elif kind == "tornado":
            task = lambda p, c: {"kind": "tornado", "bars": tornado(base, bars, seed, n)}
        else:
            ranked = {"base": base, **options}
            bounds = [tuple(b) for b in spec["uncertainty"]]
            task = lambda p, c: ranking_under_uncertainty(ranked, bounds, seed, spec.get("outer", 10), spec.get("inner", 50))
        self.launch(f"Running {kind}", task, self.show_decision)

    def show_decision(self, value):
        self.last_decision = value
        self.decision_text.setPlainText(json.dumps(value, indent=2))
        if value.get("kind") == "tornado":
            with TemporaryDirectory() as folder:
                png = Path(folder) / "tornado.png"
                render_tornado(value["bars"], png)
                self.tornado_view.setPixmap(QPixmap(str(png)).scaled(640, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                                                     Qt.TransformationMode.SmoothTransformation))
        self.statusBar().showMessage("Decision study complete")

    def inspect(self, key):
        kind, _, item = key.partition("/")
        obj = next((x for x in self.model.get(kind, []) if x["id"] == item), None)
        self.evidence.setPlainText(json.dumps({"object": key, "data": obj,
                                              "evidence": self.model.get("provenance", {}).get(key)}, indent=2))

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open case", "", "RAM cases (*.ramcase)")
        if path:
            self.open_path(Path(path))

    def open_path(self, path):
        if not path.is_file():
            raise ValueError("RAM case does not exist.")
        with open_case(path) as db:
            model = current_model(db)
            row = db.execute("SELECT id FROM run ORDER BY created_at DESC LIMIT 1").fetchone()
        if model:
            self.model = model[0]
            self.approved_hash = model[1] if model[2] else None
        self.editor = ModelEditor(self.model, approved_hash=self.approved_hash, validator=Simulator)
        self.editor.listeners.append(self.on_select)
        self.path, self.run_id = path, row[0] if row else None
        self.claims = []
        self.render(True)
        self.statusBar().showMessage(f"Opened {path.name}")
        if self.run_id:
            self.load_run()

    def save_dialog(self):
        if self.path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save RAM case", "Study.ramcase", "RAM cases (*.ramcase)")
            if not path:
                return
            self.path = Path(path if path.lower().endswith(".ramcase") else path + ".ramcase")
        with open_case(self.path) as db:
            if self.editor.model != self.model:
                self.editor.apply({"op": "replace_model", "model": self.model}, "desktop user", confirm_baseline=True)
            self.editor.save(db, "desktop user", "Saved from desktop")
            row = current_model(db)
            self.approved_hash = row[1] if row and row[2] else None
            self.editor.approved_hash = self.approved_hash
        self.statusBar().showMessage(f"Saved {self.path.name}")
        self.render()

    def load_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import model JSON", "", "Model JSON (*.json)")
        if path:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if data.get("schema") == "rammodel-topology-1":
                self.set_model(import_topology(data, data["study_basis"]), validate=False)
            else:
                self.set_model(data)

    def set_model(self, model, validate=True, confirm=None):
        if validate:
            Simulator(model)
        if model != self.model and not self.edit({"op": "replace_model", "model": model}, confirm):
            return
        self.model = self.editor.model
        self.render(True)
        if self.path:
            self.save_dialog()
        if self.run_id:
            self.load_run()

    def load_example(self):
        self.set_model(offshore_extended())

    def apply_edits(self):
        self.set_model(json.loads(self.model_editor.toPlainText()))

    def require_case(self):
        if not self.path:
            self.save_dialog()
        if not self.path:
            raise ValueError("Save a case first.")
        return self.path

    def actor(self):
        name, ok = QInputDialog.getText(self, "Engineering review", "Reviewer or operator name")
        if not ok or not name.strip():
            raise ValueError("A named reviewer or operator is required.")
        return name

    def review(self):
        with open_case(self.require_case()) as db:
            review_model(db, self.actor(), digest(self.model))
        self.approved_hash = self.editor.approved_hash = digest(self.model)
        self.render()
        self.statusBar().showMessage("Current model revision approved")

    def stage(self, directory):
        path = (QFileDialog.getExistingDirectory(self, "CSV directory") if directory else
                QFileDialog.getOpenFileName(self, "Library workbook", "", "Excel (*.xlsx)")[0])
        if path:
            staged = read_exchange(Path(path))
            actor = self.actor()
            case = self.require_case()
            with open_case(case) as db:
                warnings = import_exchange(db, staged, actor)
            self.pending = (case, actor, staged)
            self.import_text.setPlainText(json.dumps({k: len(v) for k, v in staged.items()}, indent=2) + "\n\n" + "\n".join(warnings))

    def apply_library(self):
        if not self.pending or self.path != self.pending[0]:
            raise ValueError("Preview input for this case first.")
        case, actor, staged = self.pending
        with open_case(case) as db:
            warnings = import_exchange(db, staged, actor, apply=True)
        self.pending = None
        self.import_text.appendPlainText("\nLibrary imported for review.\n" + "\n".join(warnings))

    def export_library(self):
        case = self.require_case()
        path, _ = QFileDialog.getSaveFileName(self, "Export equipment workbook", "Library.xlsx", "Excel (*.xlsx)")
        if path:
            with open_case(case) as db:
                export_exchange(db, Path(path))

    def bind(self):
        with open_case(self.require_case()) as db:
            candidate = bind_library(db, self.model)
        self.set_model(candidate)

    def run(self, seed=None, n=None):
        path = self.require_case()
        model = deepcopy(self.model)
        seed = self.seed.value() if seed is None else seed
        initial, maximum = (self.initial.value(), self.maximum.value()) if n is None else (n, n)

        def store(record):
            with open_case(path) as db:
                save_run(db, record)
            if self.path == path:
                self.run_id = record["id"]
                self.claims = []
                self.load_run()
                self.tabs.setCurrentIndex(2)

        self.launch("Simulating", lambda progress, stop: calculate(model, seed=seed, initial=initial,
                    maximum=maximum, progress=progress, cancel=stop), store)

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()

    def load_run(self):
        with open_case(self.require_case()) as db:
            if not self.run_id:
                raise ValueError("No stored run for this case.")
            record = get_run(db, self.run_id)
        result = record["result"]
        self.result_text.setPlainText(json.dumps({"stale": record["model_hash"] != digest(self.model),
            "n": result["n"], "converged": result["converged"], "metrics": result["metrics"],
            "contributors": result["contributors"]}, indent=2))
        self.show_timeline(result["preview"])
        with TemporaryDirectory() as folder:
            png = Path(folder) / "profile.png"
            _plot(record, png)
            self.chart.setPixmap(QPixmap(str(png)).scaled(870, 480, Qt.AspectRatioMode.KeepAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation))
        self.statusBar().showMessage("Run stored • " + ("convergence criterion met" if result["converged"] else "convergence not demonstrated"))

    def show_timeline(self, trace):
        intervals = trace["intervals"]
        self.timeline.setRowCount(len(intervals))
        for i, v in enumerate(intervals):
            values = [f'{v[key]:.5g}' for key in ("start", "end", "delivery", "buffer_end", "loss")]
            for j, value in enumerate(values + [", ".join(v["causes"])]):
                self.timeline.setItem(i, j, QTableWidgetItem(value))

    def compare(self):
        if not self.model.get("buffer"):
            raise ValueError("Study has no buffer.")
        capacity = self.model["buffer"]["capacity"] * 2
        if QMessageBox.question(self, "Approve experiment", f"Compare the current model with storage capacity {capacity:g}?") == QMessageBox.StandardButton.Yes:
            self.compare_capacity(capacity, self.seed.value(), self.initial.value())

    def compare_capacity(self, capacity, seed, n):
        base, option = deepcopy(self.model), deepcopy(self.model)
        option["buffer"]["capacity"] = capacity
        self.launch("Comparing", lambda progress, stop: paired_compare(base, option, seed, n, progress=progress, cancel=stop),
                    self.show_comparison)

    def show_comparison(self, value):
        self.result_text.setPlainText(json.dumps(value, indent=2))
        self.statusBar().showMessage("Comparison complete")
        self.tabs.setCurrentIndex(2)

    def settings(self):
        provider = self.provider.currentText()
        if provider == "cloud" and not self.share.isChecked():
            raise ValueError("Approve the displayed data for this cloud request.")
        self.share.setChecked(False)
        return provider, self.provider_model.toPlainText().strip()

    def extract_document(self, path=None):
        from .intake import extract
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Extract document", "", "Documents (*.txt *.md *.csv *.pdf *.xml)")
            if not path:
                return
        self.intake = extract(Path(path))
        listing = [f"{e['id']}: {e['text'][:90]}" for e in self.intake["excerpts"]]
        listing += [f"{u['id']}: {u['status'].upper()} - {u['reason']}" for u in self.intake["unsupported"]]
        self.ai_result.setPlainText("Local extraction only (nothing sent).\n" + "\n".join(listing))

    def use_excerpt(self, key=None):
        from .intake import select
        if key is None:
            key, ok = QInputDialog.getText(self, "Select excerpt", "Excerpt ID")
            if not ok:
                return
        self.excerpt_id = key
        self.excerpt.setPlainText(select(self.intake, [key])[key])

    def ai_model(self):
        provider, name = self.settings()
        source_id = getattr(self, "excerpt_id", None) or "selected-excerpt"
        prompt, excerpts, model = self.question.toPlainText(), {source_id: self.excerpt.toPlainText()}, deepcopy(self.model)
        self.launch("Interpreting evidence", lambda p, c: propose(prompt, excerpts, provider, name, model),
                    lambda v: self.ai_result.setPlainText(json.dumps(v, indent=2)))

    def ai_apply(self):
        output = json.loads(self.ai_result.toPlainText())
        source = {getattr(self, "excerpt_id", None) or "selected-excerpt": self.excerpt.toPlainText()}
        if output["base_hash"] != digest(self.model) or output["evidence_hashes"] != {k: digest(v) for k, v in source.items()}:
            raise ValueError("The model or selected evidence changed. Generate a new proposal.")
        if QMessageBox.question(self, "Apply draft", "Apply the visible proposed edits as unreviewed draft items?") == QMessageBox.StandardButton.Yes:
            model = apply_proposal(self.model, output["actions"], source)
            model.setdefault("ai_proposals", []).append(output)
            self.set_model(model, validate=False)

    def ai_plan(self):
        provider, name = self.settings()
        prompt, model = self.question.toPlainText(), deepcopy(self.model)
        def task(p, c):
            return {"base_hash": digest(model), "plan": plan_experiment(prompt, provider, name, model)}
        self.launch("Preparing experiment", task, lambda v: self.ai_result.setPlainText(json.dumps(v, indent=2)))

    def ai_execute(self):
        request = json.loads(self.ai_result.toPlainText())
        if request["base_hash"] != digest(self.model):
            raise ValueError("Prepare a plan for the current revision.")
        plan = request["plan"]
        validate_experiment(plan, self.model)
        answer = QMessageBox.question(self, "Approve experiment", json.dumps(plan, indent=2))
        if answer != QMessageBox.StandardButton.Yes:
            return
        if plan["action"] == "simulate":
            self.run(plan["seed"], plan["n"])
        elif plan["action"] == "buffer_compare":
            self.compare_capacity(plan["buffer_capacity"], plan["seed"], plan["n"])
        else:
            self.show_timeline(Simulator(self.model).replay(plan["seed"], trace=True))
            self.tabs.setCurrentIndex(2)

    def ai_narrative(self):
        provider, name = self.settings()
        run_id = self.run_id
        with open_case(self.require_case()) as db:
            catalogue = metric_catalogue(get_run(db, run_id))

        def done(value):
            self.ai_result.setPlainText(json.dumps({"run_id": run_id, "claims": value}, indent=2))

        self.launch("Drafting report narrative", lambda p, c: draft_claims(catalogue, provider, name), done)

    def run_approval(self, actor=None):
        if not self.run_id:
            raise ValueError("No stored run to approve.")
        with open_case(self.require_case()) as db:
            approve_run(db, self.run_id, actor or self.actor())
        self.statusBar().showMessage("Run approved (separate from model and narrative approval)")

    def narrative_approval(self):
        draft = json.loads(self.ai_result.toPlainText())
        if draft["run_id"] != self.run_id:
            raise ValueError("Narrative belongs to a different run.")
        with open_case(self.require_case()) as db:
            self.claims = approve_narrative(db, self.run_id, draft["claims"], self.actor())
        self.statusBar().showMessage("Narrative approved for this run")

    def report(self):
        directory = QFileDialog.getExistingDirectory(self, "Export reports")
        if directory:
            with open_case(self.require_case()) as db:
                stem = export(db, self.run_id, Path(directory), claims=self.claims, final=self.final.isChecked())
            self.statusBar().showMessage(f"Reports created: {stem.name}")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.cancel()
            self.statusBar().showMessage("Background job is still running. Close again after it returns.")
            event.ignore()
        else:
            super().closeEvent(event)


def launch(path=None):
    app = QApplication([])
    app.setStyle("Fusion")
    window = Window(path)
    window.show()
    return app.exec()
