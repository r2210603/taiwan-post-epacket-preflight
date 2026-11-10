"""Package the ePacket validator as a standalone Agent Skill."""

import argparse
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SKILL = "taiwan-post-epacket-preflight"
FILES = (
    (f"skills/{SKILL}/SKILL.md", "SKILL.md"),
    ("preflight.py", "scripts/preflight.py"),
    ("examples/batch.json", "assets/batch.json"),
    ("LICENSE", "LICENSE"),
)


def build_skill(output):
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
        for source_name, member in FILES:
            source = ROOT / source_name
            if source.resolve(strict=True) != source or not source.is_file():
                raise ValueError(f"Expected a regular source file at {source_name}")
            bundle.writestr(f"{SKILL}/{member}", source.read_bytes())

    file = output.open("xb")
    try:
        with file as destination:
            destination.write(archive.getbuffer())
    except OSError:
        output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path for a new ZIP archive")
    args = parser.parse_args()
    try:
        build_skill(args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Unable to build skill: {exc}\n")


if __name__ == "__main__":
    main()
