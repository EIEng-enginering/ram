"""Render auditable run figures and report formats."""
from datetime import UTC, datetime
import json
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .assistant import validate_claims
from .study import current_model, digest, get_run, json_text, library_hash, review_gaps

LIMITS = ("Single product per model, piecewise-constant rates, lexicographic LP routing. Calendar or operating exposure as entered. "
          "standby_pair assets use the 0.2 dedicated exponential channel; standby groups use the shared crew and spares. "
          "Loss groups record co-occurring outages and can include incidental failures; counterfactual gains are reported separately. "
          "Unmet demand is classified lost, recovered or potentially deferred only under the stated recovery policy. "
          "Economic values derive solely from entered assumptions. "
          "Mean intervals are approximate and do not account for repeated stopping checks. "
          "Results depend on study inputs. SIL/PFD and standards conformity are outside scope.")


def metric_catalogue(run):
    unit = run["basis"]["volume_unit"]
    units = {"efficiency": "fraction", "delivered": unit, "shortfall": unit, "buffer_end": unit,
             "crew_utilisation": "fraction", "lost": unit, "recovered": unit, "deferred": unit,
             "lost_value": (run["result"].get("economics") or {}).get("currency", "currency")}
    return {k: {**v, "unit": units[k]} for k, v in run["result"]["metrics"].items()}


def approve_run(db, run_id, actor):
    """Named engineering approval of one stored calculation for the current model revision."""
    if not actor.strip():
        raise ValueError("Enter run reviewer.")
    run = get_run(db, run_id)
    current = current_model(db)
    if not current or current[1] != run["model_hash"]:
        raise ValueError("Only a run of the current model revision can be approved.")
    if not run["result"]["converged"]:
        raise ValueError("Convergence was not demonstrated for this run.")
    db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
               (run_id, "approve run", actor.strip(), datetime.now(UTC).isoformat(), run["model_hash"]))


def save_narrative_edit(db, run_id, claims, actor, origin="engineer"):
    """Persist each narrative edit with its origin (engineer or AI provider) for audit."""
    if not actor.strip():
        raise ValueError("Enter the editor name.")
    run = get_run(db, run_id)
    claims = validate_claims(claims, metric_catalogue(run))
    db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
               (run_id, "narrative edit", actor.strip(), datetime.now(UTC).isoformat(),
                json_text({"origin": origin, "claims": claims})))
    return claims


def narrative_history(db, run_id):
    return [{"actor": a, "at": t, **json.loads(d)} for a, t, d in db.execute(
        "SELECT actor, created_at, detail FROM review_log WHERE target=? AND action='narrative edit' ORDER BY id",
        (run_id,))]


def approve_narrative(db, run_id, claims, actor):
    if not actor.strip():
        raise ValueError("Enter narrative reviewer.")
    run = get_run(db, run_id)
    claims = validate_claims(claims, metric_catalogue(run))
    db.execute("INSERT INTO review_log (target,action,actor,created_at,detail) VALUES (?,?,?,?,?)",
               (run_id, "approve narrative", actor.strip(), datetime.now(UTC).isoformat(), digest(claims)))
    return claims


def export(db, run_id, directory: Path, *, claims=None, final=False):
    run = get_run(db, run_id)
    current = current_model(db)
    catalogue = metric_catalogue(run)
    claims = validate_claims(claims or [], catalogue)
    stale = not current or current[1] != run["model_hash"]
    gaps = review_gaps(run["model"])
    reviewed = bool(current and current[2] and not stale and not gaps)
    run_approver = db.execute("SELECT actor FROM review_log WHERE target=? AND action='approve run' AND detail=? "
                              "ORDER BY id DESC LIMIT 1", (run_id, run["model_hash"])).fetchone()
    if final:
        if stale or not reviewed or not run["result"]["converged"]:
            raise ValueError("Final export requires current engineer review and a converged run.")
        if not run_approver:
            raise ValueError("Final export requires a named approval of this run (separate from model approval).")
        if claims and not db.execute("SELECT 1 FROM review_log WHERE target=? AND action=? AND detail=?",
                                     (run_id, "approve narrative", digest(claims))).fetchone():
            raise ValueError("Approve this exact narrative before final export.")
    status = "Engineer-reviewed results – not independently verified" if final else "DRAFT"
    if not final and reviewed and run_approver:
        status = "DRAFT (model and run approved; narrative/final export pending)"
    if stale:
        status += " | STALE"
    if run["model"].get("example"):
        status += " | EXAMPLE DATA"
    if not run["result"]["converged"]:
        status += " | CONVERGENCE NOT DEMONSTRATED"
    if gaps:
        status += " | UNRESOLVED ASSUMPTIONS"
    if run.get("library_hash") and run["library_hash"] != library_hash(db):
        status += " | LIBRARY CHANGED SINCE RUN"
    lines = [
        ("Report status", status), ("Study and basis", run["model"].get("basis", "Unspecified")),
        ("Run", run_id), ("Method", run["method"]), ("Model SHA256", run["model_hash"]),
        ("Code SHA256", run["code_hash"]), ("Environment", json_text(run["environment"])),
        ("Replications / seed", f"{run['result']['n']} / {run['result']['seed']}"),
        ("Horizon / target", f"{run['basis']['horizon_h']} h / {run['basis']['target_rate']} {run['basis']['volume_unit']}/h"),
        ("Review gaps", "; ".join(gaps) or "None recorded"), ("Methods and limits", LIMITS),
    ]
    basis = run["basis"]
    result = run["result"]
    lines.insert(9, ("Method profile", run.get("method_profile", "0.2 alpha record")))
    if "contractual_demand" in basis:
        lines.append(("Production bases", f"contractual demand {basis['contractual_demand']:.8g}; no-failure delivery "
                      f"{basis['no_failure_delivery']:.8g}; mean actual delivery {result['metrics']['delivered']['mean']:.8g} "
                      f"{basis['volume_unit']}"))
    if result.get("stop_reason"):
        lines.append(("Stop reason", result["stop_reason"]))
    if result.get("diagnostics", {}).get("note"):
        lines.append(("Sampling diagnostics", result["diagnostics"]["note"].strip()))
    if "balance_max_abs_residual" in result:
        lines.append(("Volume balance", f"max |supply - delivered - inventory change - yield loss| over replications = "
                      f"{result['balance_max_abs_residual']:.3g} {basis['volume_unit']}"))
    if result.get("economics"):
        e = result["economics"]
        lines.append(("Economic basis", f"{e['currency']}, {e['cost_basis']}, {e['value_per_unit']} per unit, "
                      f"discount {e['discount_rate']}/yr, {e['timing']}; source: {e['source']}"))
    lines.append(("Uncertainty kinds", "P10/P50/P90 = per-run spread; 95% mean CI = sampling; option intervals = paired "
                  "deltas; input uncertainty reported separately where run"))
    if final:
        lines.append(("Model reviewer", current[2]))
        lines.append(("Run approver", run_approver[0]))
    metrics = [[k, v["unit"], *[f"{v[x]:.8g}" for x in ("mean", "p10", "p50", "p90")],
                f"{v['ci95'][0]:.8g} to {v['ci95'][1]:.8g}"] for k, v in catalogue.items()]
    headers = ["Metric", "Unit", "Mean", "P10", "P50", "P90", "95% mean CI"]
    narrative = [[c["text"], c["metric"], f"{catalogue[c['metric']]['mean']:.8g} {catalogue[c['metric']]['unit']}"]
                 for c in claims]
    evidence = [(k, str(v) if isinstance(v, str) else json_text(v)) for k, v in sorted(run["model"].get("provenance", {}).items())]
    contributors = [(group, item, f"{value:.8g}") for group, items in run["result"]["contributors"].items()
                    for item, value in items.items()]
    comparisons = []
    for key, item in run.get("analysis", {}).items():
        if isinstance(item, dict) and "difference" in item:
            d = item["difference"]
            resolved = d.get("significant", abs(d["mean"]) > (d["ci95"][1] - d["ci95"][0]) / 2)
            comparisons.append((key.replace("_", " "), f"{100*d['mean']:+.5f}",
                                f"{100*d['ci95'][0]:+.5f} to {100*d['ci95'][1]:+.5f}"
                                + ("" if resolved else " (not resolved: interval includes zero)")))
    counterfactual = [(c["equipment"], c["mode"], f"{100 * c['gain']['mean']:+.5f}")
                      for c in run.get("analysis", {}).get("criticality", [])]
    periods = [[k, *[f"{v.get(f, 0):.6g}" for f in ("hours", "demand", "delivered", "shortfall", "recovered", "lost")]]
               for k, v in run["result"].get("periods_mean", {}).items()]
    period_headers = ["Month", "Hours", "Demand", "Delivered", "Shortfall", "Recovered", "Lost"]
    directory.mkdir(exist_ok=True, parents=True)
    stem = directory / f"ram_{run_id[:10]}"
    chart = stem.with_name(stem.name + "_profile.png")
    _plot(run, chart)
    diagram = stem.with_name(stem.name + "_model.png")
    _diagram(run["model"], diagram)
    tornado_png = None
    if run.get("analysis", {}).get("tornado"):
        from .decision import render_tornado
        tornado_png = stem.with_name(stem.name + "_tornado.png")
        render_tornado(run["analysis"]["tornado"], tornado_png)
    stem.with_suffix(".json").write_text(json.dumps(
        {"status": status, "limits": LIMITS, "claims": claims, "run": run}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    book = Workbook()
    book.active.title = "Basis"
    sheets = {"Basis": [["Field", "Value"], *lines], "Metrics": [headers, *metrics],
              "Evidence": [["Object", "Source"], *evidence], "Contributors": [["Group", "Item", "Mean"], *contributors],
              "Narrative": [["Draft text", "Metric", "Value"], *narrative],
              "Options": [["Option", "Change (percentage points)", "95% paired CI"], *comparisons],
              "Periods": [["Month", "Hours", "Demand", "Delivered", "Shortfall", "Recovered", "Lost"],
                          *[[k, v.get("hours", 0), v.get("demand", 0), v.get("delivered", 0), v.get("shortfall", 0),
                             v.get("recovered", 0), v.get("lost", 0)] for k, v in result.get("periods_mean", {}).items()]],
              "Convergence": [["Replications", "Mean efficiency", "95% CI halfwidth"],
                              *[[v["n"], v["mean"], v["halfwidth"]] for v in run["result"]["convergence"]]]}
    for name, rows in sheets.items():
        ws = book[name] if name in book else book.create_sheet(name)
        for row in rows:
            ws.append(row)
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.freeze_panes = "A2"
    loss = run["result"]["contributors"]["loss_groups"]
    if loss:
        ws = book.create_sheet("Loss groups")
        ws.append(("Coincident outages", "Mean shortfall"))
        for name, value in loss.items():
            ws.append((name, value))
            ws.cell(ws.max_row, 1).data_type = "s"
        plot = BarChart()
        plot.type = "bar"
        plot.title = "Coincident outage groups"
        plot.add_data(Reference(ws, min_col=2, min_row=1, max_row=min(ws.max_row, 11)), titles_from_data=True)
        plot.set_categories(Reference(ws, min_col=1, min_row=2, max_row=min(ws.max_row, 11)))
        ws.add_chart(plot, "D2")
    book.save(stem.with_suffix(".xlsx"))
    doc = Document()
    doc.add_heading("RAM and production availability", 0)
    for title, value in lines:
        doc.add_paragraph(f"{title}: {value}")
    for title, columns, rows in (("Metrics", headers, metrics), ("Narrative", ["Claim", "Metric", "Value"], narrative),
                                 ("Contributors", ["Group", "Item", "Mean"], contributors),
                                 ("Evidence", ["Object", "Source"], evidence),
                                 ("Options", ["Option", "Change (percentage points)", "95% paired CI"], comparisons),
                                 ("Counterfactual gains (one mode removed; nonadditive, not loss shares)",
                                  ["Equipment", "Mode", "Gain (percentage points)"], counterfactual),
                                 ("Monthly periods (mean per replication)", period_headers, periods)):
        if not rows:
            continue
        doc.add_heading(title, 1)
        table = doc.add_table(rows=1, cols=len(columns))
        table.style = "Light Shading Accent 1"
        for cell, name in zip(table.rows[0].cells, columns):
            cell.text = name
        for row in rows:
            for cell, value in zip(table.add_row().cells, row):
                cell.text = value
    doc.add_heading("Production flow", 1)
    doc.add_picture(str(diagram), width=Inches(6))
    doc.add_picture(str(chart), width=Inches(6))
    if tornado_png:
        doc.add_heading("Sensitivity tornado", 1)
        doc.add_picture(str(tornado_png), width=Inches(6))
    doc.save(stem.with_suffix(".docx"))
    styles = getSampleStyleSheet()
    story = [Paragraph("RAM and production availability", styles["Title"])]
    for title, value in lines:
        story.append(Paragraph(f"<b>{escape(title)}</b>: {escape(value)}", styles["BodyText"]))
        story.append(Spacer(1, 5))
    cells = [[Paragraph(escape(v), styles["BodyText"]) for v in row] for row in [headers, *metrics]]
    table = Table(cells, colWidths=[87, 58, 52, 46, 46, 46, 90], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#cde3ef")),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [table, Spacer(1, 12), Image(str(diagram), width=445, height=150),
              Spacer(1, 7), Image(str(chart), width=445, height=222)]
    if tornado_png:
        story += [Spacer(1, 7), Image(str(tornado_png), width=445, height=min(400, 445 * 0.075 * (len(run["analysis"]["tornado"]) * 0.6 + 1.4)))]
    for rows, label in ((narrative, "Narrative"), (comparisons, "Options: change in percentage points and paired CI"),
                        (counterfactual, "Counterfactual gains (nonadditive; separate from coincident loss groups)"),
                        (periods, "Monthly periods: month | hours | demand | delivered | shortfall | recovered | lost"),
                        (contributors, "Contributors"), (evidence, "Evidence")):
        if rows:
            story.append(Paragraph(label, styles["Heading2"]))
            story.extend(Paragraph(escape(" | ".join(row)), styles["BodyText"]) for row in rows)
    SimpleDocTemplate(str(stem.with_suffix(".pdf"))).build(story)
    return stem


def _plot(run, path):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8, 4), layout="constrained")
    FigureCanvasAgg(fig)
    ax, buffer_ax = fig.subplots(2)
    intervals = (run["result"].get("preview") or {}).get("intervals", [])
    for metric, name, color in (("delivery", "Delivered rate", "#006986"), ("target", "Target", "#b65218")):
        if intervals:
            x = [i["start"] for i in intervals] + [intervals[-1]["end"]]
            y = [i[metric] for i in intervals] + [intervals[-1][metric]]
            ax.step(x, y, where="post", label=name, color=color)
    if intervals:
        ax.legend(loc="upper right")
        buffer_ax.plot([intervals[0]["start"]] + [i["end"] for i in intervals],
                       [intervals[0]["buffer_start"]] + [i["buffer_end"] for i in intervals], color="#126f55")
    ax.set_ylabel(run["basis"]["volume_unit"] + "/h")
    ax.set_title("Replication 0 • production and storage")
    buffer_ax.set_ylabel(run["basis"]["volume_unit"])
    buffer_ax.set_xlabel("Calendar hours")
    fig.savefig(path, dpi=120)


def _diagram(model, path):
    from collections import defaultdict
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    chart = Figure(figsize=(8.8, 3), layout="constrained")
    FigureCanvasAgg(chart)
    ax = chart.subplots()
    ax.set_axis_off()
    ax.set_title("Production flow and equipment IDs", fontsize=11, loc="left")
    edges = model["edges"]
    nodes = sorted({edge[k] for edge in edges for k in ("from", "to")})
    levels = dict.fromkeys(nodes, 0)
    for _ in nodes:
        for edge in edges:
            levels[edge["to"]] = max(levels[edge["to"]], levels[edge["from"]] + 1)
    lanes, positions = defaultdict(list), {}
    for node in nodes:
        lanes[levels[node]].append(node)
    for level, members in lanes.items():
        for i, node in enumerate(members):
            positions[node] = (level, i - (len(members) - 1) / 2)
    groups = defaultdict(list)
    for edge in edges:
        groups[(edge["from"], edge["to"])].append(edge)
    for (a, b), group in groups.items():
        x, y = positions[a]
        xx, yy = positions[b]
        label = "\n".join(f"{e['id']}  {e['capacity']:g}" for e in group[:8])
        ax.annotate("", (xx - .13, yy), (x + .13, y), arrowprops={"arrowstyle": "->", "color": "#25647c"})
        ax.text((x + xx) / 2, (y + yy) / 2 + .09, label, ha="center", va="bottom", fontsize=7)
    for node, (x, y) in positions.items():
        ax.text(x, y, node, ha="center", va="center", fontsize=8,
                bbox={"boxstyle": "round,pad=.35", "facecolor": "#e5f1f6", "edgecolor": "#25647c"})
    ax.set_xlim(-.4, max(levels.values()) + .4)
    ax.set_ylim(min(y for _, y in positions.values()) - .4, max(y for _, y in positions.values()) + .72)
    chart.savefig(path, dpi=120)
