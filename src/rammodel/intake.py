"""Local, offline document intake producing located excerpts for review or AI proposal.

Supported in this release:
* plain text, Markdown and CSV - excerpts located by line range;
* PDF with a text layer (via ``pypdf``) - excerpts located by page and line range.

Not supported (reported, never guessed):
* scanned PDF pages or raster drawings without a text layer - OCR is not bundled;
  the page is returned with status ``needs_ocr`` and no text;
* DEXPI XML - no official fixture was available, so no mapping is claimed;
* the project's P&ID Reader export - integration requires an authorised sample; use the
  neutral ``rammodel-topology-1`` handoff (engineering_import.import_topology) meanwhile.

Document text is data. Nothing here interprets instructions found in a document.
"""
from hashlib import sha256
from pathlib import Path

TEXT = {".txt", ".md", ".csv"}


def _chunks(lines, prefix, size):
    out = []
    for start in range(0, len(lines), size):
        block = lines[start:start + size]
        text = "\n".join(block).strip()
        if text:
            out.append({"id": f"{prefix}:L{start + 1}-{start + len(block)}", "text": text, "status": "text"})
    return out


def extract(path: Path, lines_per_excerpt=20):
    path = Path(path)
    data = path.read_bytes()
    record = {"file": path.name, "sha256": sha256(data).hexdigest(), "excerpts": [], "unsupported": []}
    suffix = path.suffix.lower()
    if suffix in TEXT:
        record["excerpts"] = _chunks(data.decode("utf-8-sig").splitlines(), path.name, lines_per_excerpt)
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            record["unsupported"].append({"id": path.name, "status": "blocked",
                                          "reason": "pypdf is not installed; PDF text extraction unavailable."})
            return record
        reader = PdfReader(str(path))
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if not text.strip():
                record["unsupported"].append({"id": f"{path.name}#p{number}", "status": "needs_ocr",
                                              "reason": "No text layer (scanned page or drawing). OCR is not bundled; "
                                                        "transcribe the relevant content or supply a text export."})
                continue
            record["excerpts"] += _chunks(text.splitlines(), f"{path.name}#p{number}", lines_per_excerpt)
    elif suffix == ".xml" and b"dexpi" in data[:4000].lower():
        record["unsupported"].append({"id": path.name, "status": "unsupported",
                                      "reason": "DEXPI mapping is not implemented: no official documented version and "
                                                "representative fixture were available for this release."})
    else:
        record["unsupported"].append({"id": path.name, "status": "unsupported",
                                      "reason": f"File type {suffix or '(none)'} is not supported for intake."})
    return record


def select(record, ids):
    """Only explicitly selected excerpts may be sent to a provider."""
    chosen = {e["id"]: e["text"] for e in record["excerpts"] if e["id"] in set(ids)}
    missing = set(ids) - chosen.keys()
    if missing:
        raise ValueError(f"Unknown excerpt IDs: {', '.join(sorted(missing))}.")
    return chosen
