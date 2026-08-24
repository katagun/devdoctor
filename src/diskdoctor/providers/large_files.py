"""Large-files provider: surface individual big files in the user's common
drop-zone directories (Desktop, Documents, Movies, Pictures) that no other
provider would catch.

Every other provider models a *directory* representing a known cache. This
one models *individual files* because stray ISOs, video exports, and backup
archives are usually one-off items the user forgot about. Each file becomes
its own entry with an advice-only recipe — we never auto-rm user data.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider, _stat_kwargs
from diskdoctor.types import Entry, Risk

# Files below this threshold aren't worth surfacing individually. Tuned to
# catch ISOs / VM images / large video exports while ignoring normal
# documents and installers.
_MIN_BYTES = 500 * 1024 * 1024  # 500 MB

# Default scan roots — covers where people actually dump large one-off files.
# ~/Downloads is intentionally excluded because the downloads provider handles
# it with a different recipe (the advice there is about the folder as a whole).
_DEFAULT_ROOTS = ("~/Desktop", "~/Documents", "~/Movies", "~/Pictures")

# Don't descend into directories known to belong to other providers or to
# system state — keeps the walk fast and the results meaningful. Names only;
# the skip applies at any depth by comparing the dirname.
_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".cache",
        "Caches",
        "Library",  # on macOS ~/Library is enormous and covered elsewhere
    }
)


class LargeFilesProvider(Provider):
    name = "large-files"
    description = (
        "Individual files >= 500 MB in Desktop / Documents / Movies / Pictures — "
        "often forgotten VM images, ISOs, video exports, or backup archives"
    )
    platforms = ("darwin", "linux")
    risk = Risk.DANGEROUS  # user data; never auto-delete
    required_binary = None
    details = (
        "Walks ~/Desktop, ~/Documents, ~/Movies, and ~/Pictures looking for "
        "individual files >= 500 MB — typically forgotten ISOs, VM images, "
        "video exports, or backup archives. Each match is advice-only; the recipe "
        "echoes a review prompt rather than running rm."
    )

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        for raw in _DEFAULT_ROOTS:
            root = Path(os.path.expanduser(raw))
            if not root.exists():
                continue
            try:
                root_dev = root.lstat().st_dev
            except OSError:
                continue
            for file_path, size, mtime in _walk_for_large_files(root, root_dev):
                path_str = str(file_path)
                quoted = shlex.quote(path_str)
                # Advice-only — the UI renders this as bulleted sentences.
                msg = (
                    f"Large file at {path_str} ({_human(size)}). "
                    f"Review it before deleting — it's in a user-data folder and may matter. "
                    f"Preview with: ls -lh {quoted}. "
                    f"If it's genuinely disposable, delete with: rm {quoted}. "
                    f"Do NOT rm -rf anything above this file."
                )
                # Quote the WHOLE message, not just the paths inside it. A
                # filename with an apostrophe (e.g. "John's.iso") or a crafted
                # name like "x'$(...)'.iso" would otherwise break out of a
                # hand-built `echo '...'` — crashing shlex.split at cleanup
                # time and, worse, injecting shell into the reviewable script
                # emitted by build_script.
                recipe_line = f"echo {shlex.quote(msg)}"
                entries.append(
                    Entry(
                        provider=self.name,
                        id=path_str,
                        path=file_path,
                        label=path_str,
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=[recipe_line],
                        **_stat_kwargs(file_path),
                    )
                )
        return entries


def _walk_for_large_files(root: Path, root_dev: int) -> list[tuple[Path, int, float | None]]:
    hits: list[tuple[Path, int, float | None]] = []

    def on_error(_err: OSError) -> None:
        return None

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
        dp = Path(dirpath)

        # Prune by name (node_modules, etc.) and by device boundary.
        keep: list[str] = []
        for name in dirnames:
            if name in _SKIP_DIR_NAMES or name.startswith("."):
                continue
            sub = dp / name
            try:
                if sub.lstat().st_dev != root_dev:
                    continue
            except OSError:
                continue
            keep.append(name)
        dirnames[:] = keep

        for fname in filenames:
            fp = dp / fname
            try:
                st = fp.lstat()
            except OSError:
                continue
            # Symlinks: st_mode check — follow-free walk handles this, but
            # lstat on a symlink gives the link's own size (small), which
            # self-filters below the threshold.
            blocks = getattr(st, "st_blocks", 0) * 512
            size = min(st.st_size, blocks) if blocks else st.st_size
            if size < _MIN_BYTES:
                continue
            hits.append((fp, size, st.st_mtime))
    return hits


_UNIT_STEP = 1024


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < _UNIT_STEP:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n = int(n / _UNIT_STEP)
    return f"{n}TB"


__all__ = ["LargeFilesProvider"]
