"""Cross-check exported JSON, XLSX, DOCX and PDF reports for numerical and label agreement.

For every report set under the given folders: the status label, run id, method and every metric mean
(8 significant figures, the report format) must agree between JSON (source of truth), the XLSX
Metrics sheet, the DOCX text/tables and the PDF text layer.
"""
import json
import re
from pathlib import Path
import sys

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


def check(json_path):
    stem = json_path.with_suffix("")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    run = data["run"]
    wb = load_workbook(stem.with_suffix(".xlsx"), read_only=True)
    try:  # read-only workbooks hold the file open; close so Windows can delete it
        basis = {r[0]: r[1] for r in wb["Basis"].iter_rows(values_only=True)}
        rows = list(wb["Metrics"].iter_rows(values_only=True))
    finally:
        wb.close()
    metrics = {r[0]: r[2] for r in rows}
    units = {r[0]: r[1] for r in rows}
    doc = Document(stem.with_suffix(".docx"))
    docx = "\n".join([p.text for p in doc.paragraphs] +
                     [c.text for t in doc.tables for row in t.rows for c in row.cells])
    pdf = "\n".join(page.extract_text() or "" for page in PdfReader(stem.with_suffix(".pdf")).pages)
    pdf_flat = pdf.replace("\n", "")      # labels can wrap mid-token
    problems = []
    for label, value in (("status", data["status"]), ("run", run["id"]), ("method", run["method"])):
        for name, text in (("docx", docx), ("pdf", pdf_flat)):
            if str(value) not in text:
                problems.append(f"{label} {value!r} missing from {name}")
    if basis.get("Report status") != data["status"]:
        problems.append("XLSX status differs")
    count = 0
    for name, stats in run["result"]["metrics"].items():
        expected = f"{stats['mean']:.8g}"
        count += 1
        if metrics.get(name) != expected:
            problems.append(f"XLSX {name} {metrics.get(name)} != {expected}")
        if not re.search(r"(?<![\d.])" + re.escape(expected) + r"(?![\d])", docx):
            problems.append(f"docx lacks {name} mean {expected}")
        # PDF table cells wrap long numbers, so match the row prefix "<metric><unit><mean>" with newlines removed.
        row = re.escape(f"{name}{units.get(name, '')}{expected}")
        if not re.search(row, pdf_flat):  # next cell (P10) follows directly, so no right boundary
            problems.append(f"pdf lacks {name} mean {expected}")
    return count, problems


def main(folders):
    failures = 0
    for folder in folders:
        for json_path in sorted(Path(folder).rglob("ram_*.json")):
            count, problems = check(json_path)
            print(f"{'PASS' if not problems else 'FAIL'} {json_path} ({count} metrics, status/run/method labels)")
            for p in problems:
                print("   ", p)
            failures += bool(problems)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["examples"]))
