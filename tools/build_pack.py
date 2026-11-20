"""Create a return ZIP from the source tree and chosen example."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    parser = ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    members = []
    safe = {"docs", "src", "tests", "tools", "TEST_RESULTS", "examples"}
    for file in root.rglob("*"):
        if not file.is_file():
            continue
        parts = file.relative_to(root).parts
        if ("__pycache__" in parts or any(p.endswith(".egg-info") for p in parts) or
                parts[:2] == ("examples", "Offshore")):
            continue
        if (parts[0] in safe or (len(parts) == 1 and file.suffix in {".md", ".toml", ".ps1"})) and not file.name.startswith("."):
            members.append(file)
    members.sort(key=lambda item: item.relative_to(root).as_posix())
    lines = [f"{sha256(file.read_bytes()).hexdigest()}  {file.relative_to(root).as_posix()}" for file in members]
    manifest = root / "SHA256SUMS"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
        for file in [*members, manifest]:
            archive.write(file, file.relative_to(root).as_posix())
    with ZipFile(args.output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Corrupt archive")
    print(f"Packaged {len(members)} files plus SHA256SUMS.")


if __name__ == "__main__":
    main()
