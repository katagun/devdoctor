from __future__ import annotations

import os
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk


class LMStudioProvider(Provider):
    name = "lm-studio-models"
    description = "LM Studio downloaded models, grouped by <publisher>/<model>"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = None

    def discover(self) -> list[Entry]:
        root = Path(os.path.expanduser("~/.cache/lm-studio/models"))
        if not root.exists():
            return []
        entries: list[Entry] = []
        for publisher_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for model_dir in sorted(m for m in publisher_dir.iterdir() if m.is_dir()):
                size, _ = size_path(model_dir)
                mid = f"{publisher_dir.name}/{model_dir.name}"
                try:
                    mtime = model_dir.lstat().st_mtime
                except OSError:
                    mtime = None
                entries.append(
                    Entry(
                        provider=self.name,
                        id=mid,
                        path=model_dir,
                        label=mid,
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=[f"rm -rf {shlex.quote(str(model_dir))}"],
                    )
                )
        return entries
