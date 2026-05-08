from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIST = ROOT / "src" / "diskdoctor" / "web" / "_static" / "dist"
DATA_FILE = ROOT / "src" / "diskdoctor" / "data" / "paths.yaml"
BUILD_DIR = ROOT / ".build" / "pyinstaller"
ENTRY_FILE = BUILD_DIR / "diskdoctor_entry.py"
DIST_BACKEND = ROOT / "web" / "dist-backend"
BACKEND_BINARY = DIST_BACKEND / "diskdoctor"


def _data_arg(source: Path, target: str) -> str:
    return f"{source}{os.pathsep}{target}"


def build_pyinstaller_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "diskdoctor",
        "--distpath",
        str(DIST_BACKEND),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT / "src"),
        "--add-data",
        _data_arg(DATA_FILE, "diskdoctor/data"),
        "--add-data",
        _data_arg(WEB_DIST, "diskdoctor/web/_static/dist"),
        "--collect-submodules",
        "uvicorn",
        str(ENTRY_FILE),
    ]


def main() -> None:
    if not (WEB_DIST / "index.html").is_file():
        raise SystemExit("Missing bundled web UI. Run `cd web && npm run build` first.")
    if not DATA_FILE.is_file():
        raise SystemExit(f"Missing provider registry data: {DATA_FILE}")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    ENTRY_FILE.write_text(
        "from diskdoctor.cli import main\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    if BACKEND_BINARY.exists():
        BACKEND_BINARY.unlink()

    subprocess.run(build_pyinstaller_command(), cwd=ROOT, check=True)
    if not BACKEND_BINARY.is_file():
        raise SystemExit(f"PyInstaller finished without creating {BACKEND_BINARY}")
    BACKEND_BINARY.chmod(BACKEND_BINARY.stat().st_mode | 0o755)
    shutil.rmtree(BUILD_DIR / "work", ignore_errors=True)
    print(BACKEND_BINARY)


if __name__ == "__main__":
    main()
