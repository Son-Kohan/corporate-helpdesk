#!/usr/bin/env python3
import argparse
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIRECTORIES = ("app", "deploy", "scripts", "static")
ROOT_FILES = (
    ".env.example",
    "README.md",
    "USER_GUIDE.md",
    "VERSION",
    "requirements.txt",
)


def should_include(path: Path) -> bool:
    return "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}


def add_file(archive: zipfile.ZipFile, path: Path, prefix: str, relative: Path | None = None) -> None:
    relative = relative or path.relative_to(ROOT)
    info = zipfile.ZipInfo.from_file(path, f"{prefix}/{relative.as_posix()}")
    if path.suffix == ".sh":
        info.external_attr = 0o100755 << 16
    with path.open("rb") as source:
        archive.writestr(info, source.read())


def build_release(output_dir: Path, include_data: bool) -> Path:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    suffix = "-with-data" if include_data else ""
    release_name = f"helpdesk-{version}-raspberry-pi{suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{release_name}.zip"

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename in ROOT_FILES:
            add_file(archive, ROOT / filename, release_name)
        for directory in DIRECTORIES:
            for path in sorted((ROOT / directory).rglob("*")):
                if path.is_file() and should_include(path):
                    add_file(archive, path, release_name)
        if include_data:
            database = ROOT / "helpdesk.db"
            if not database.exists():
                raise FileNotFoundError("helpdesk.db was not found")
            with tempfile.TemporaryDirectory() as temp_dir:
                snapshot = Path(temp_dir) / "helpdesk.db"
                with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as destination:
                    source.backup(destination)
                add_file(archive, snapshot, release_name, Path("helpdesk.db"))

    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Raspberry Pi release archive.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    parser.add_argument("--include-data", action="store_true")
    args = parser.parse_args()
    print(build_release(args.output_dir.resolve(), args.include_data))


if __name__ == "__main__":
    main()
