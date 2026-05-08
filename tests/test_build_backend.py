from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_build_backend() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_backend",
        ROOT / "scripts" / "build_backend.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_command_bundles_static_ui_and_provider_registry() -> None:
    build_backend = _load_build_backend()

    cmd = build_backend.build_pyinstaller_command()

    assert "--onefile" in cmd
    assert cmd[cmd.index("--name") + 1] == "diskdoctor"
    assert cmd[cmd.index("--distpath") + 1] == str(ROOT / "web" / "dist-backend")
    assert (
        f"{ROOT / 'src' / 'diskdoctor' / 'data' / 'paths.yaml'}{os.pathsep}diskdoctor/data" in cmd
    )
    assert (
        f"{ROOT / 'src' / 'diskdoctor' / 'web' / '_static' / 'dist'}"
        f"{os.pathsep}diskdoctor/web/_static/dist" in cmd
    )
    assert cmd[cmd.index("--collect-submodules") + 1] == "uvicorn"
