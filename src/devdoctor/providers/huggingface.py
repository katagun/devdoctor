from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import size_path_detailed
from devdoctor.types import DeletePathAction, DiskUsage, Entry, Risk

_REPO_RE = re.compile(r"^(models|datasets)--(.+)$")


class HuggingFaceProvider(Provider):
    name = "huggingface-hub"
    family = "local-ai"
    description = "HuggingFace hub cache (models and datasets)"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = None
    details = (
        "Scans ~/.cache/huggingface/hub for `models--<user>--<repo>` and "
        "`datasets--<user>--<repo>` directories. Each repo becomes one entry; "
        "cleanup `rm -rf`s the whole repo cache."
    )

    def discover(self) -> list[Entry]:
        hub = Path(os.path.expanduser("~/.cache/huggingface/hub"))
        if not hub.exists():
            return []
        entries: list[Entry] = []
        for repo in sorted(hub.iterdir()):
            if not repo.is_dir():
                continue
            m = _REPO_RE.match(repo.name)
            if not m:
                continue
            kind = m.group(1)
            repo_id = m.group(2).replace("--", "/")
            sizing = size_path_detailed(repo)
            size = sizing.allocated_bytes
            self._note_skipped(list(sizing.skipped_paths))
            label = f"{kind}:{repo_id}"
            try:
                mtime: float | None = repo.lstat().st_mtime
            except OSError:
                mtime = None
            entries.append(
                Entry(
                    provider=self.name,
                    id=label,
                    path=repo,
                    label=label,
                    size_bytes=size,
                    mtime=mtime,
                    risk=self.risk,
                    recipe=[f"rm -rf {shlex.quote(str(repo))}"],
                    usage=DiskUsage(size, size),
                    actions=(DeletePathAction(repo),),
                    hardlinks=sizing.hardlinks,
                    **_stat_kwargs(repo),
                )
            )
        return entries
