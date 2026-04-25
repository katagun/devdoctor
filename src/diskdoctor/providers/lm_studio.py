from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

import yaml

from diskdoctor.providers.base import Provider, _stat_kwargs
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk


class LMStudioProvider(Provider):
    """LM Studio downloaded models.

    Handles two on-disk layouts:

    1. **Legacy (LM Studio <= v0.2)**: ``{home}/models/<publisher>/<model>/``
       contains the actual GGUF/MLX files.
    2. **Hub (LM Studio v0.3+)**: ``{home}/hub/models/<publisher>/<model>/model.yaml``
       is a manifest that points to one or more HuggingFace repos; the actual
       bytes live under ``~/.cache/huggingface/hub/models--<user>--<repo>``.
       The manifest itself is ~1 KB; the reported size sums the HF cache
       entries it references so the user sees the true disk cost.

    ``{home}`` is read from ``~/.lmstudio-home-pointer`` when present (LM
    Studio writes this to keep its home portable), otherwise falls back to
    ``~/.cache/lm-studio``.
    """

    name = "lm-studio-models"
    description = "LM Studio downloaded models, grouped by <publisher>/<model>"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = None
    details = (
        "Handles LM Studio's two on-disk layouts: legacy `<home>/models/<pub>/<model>/` "
        "and v0.3+ hub manifests under `<home>/hub/models/`. For hub entries, the size "
        "sums the linked HuggingFace cache so the user sees true disk cost."
    )

    def discover(self) -> list[Entry]:
        home = _resolve_home()
        entries: list[Entry] = []

        legacy_root = home / "models"
        if legacy_root.exists():
            entries.extend(_scan_legacy(legacy_root, self.name, self.risk))

        hub_root = home / "hub" / "models"
        if hub_root.exists():
            entries.extend(_scan_hub(hub_root, self.name, self.risk))

        return entries


def _resolve_home() -> Path:
    pointer = Path("~/.lmstudio-home-pointer").expanduser()
    if pointer.is_file():
        try:
            target = pointer.read_text().strip()
            if target:
                return Path(os.path.expanduser(target))
        except OSError:
            pass
    return Path("~/.cache/lm-studio").expanduser()


def _scan_legacy(root: Path, provider_name: str, risk: Risk) -> list[Entry]:
    entries: list[Entry] = []
    for pub_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for model_dir in sorted(m for m in pub_dir.iterdir() if m.is_dir()):
            size, _ = size_path(model_dir)
            if size == 0:
                # Empty publisher/model dirs left behind by uninstalls — skip.
                continue
            mid = f"{pub_dir.name}/{model_dir.name}"
            try:
                mtime: float | None = model_dir.lstat().st_mtime
            except OSError:
                mtime = None
            entries.append(
                Entry(
                    provider=provider_name,
                    id=mid,
                    path=model_dir,
                    label=mid,
                    size_bytes=size,
                    mtime=mtime,
                    risk=risk,
                    recipe=[f"rm -rf {shlex.quote(str(model_dir))}"],
                    **_stat_kwargs(model_dir),
                )
            )
    return entries


def _scan_hub(root: Path, provider_name: str, risk: Risk) -> list[Entry]:
    entries: list[Entry] = []
    hf_hub = Path("~/.cache/huggingface/hub").expanduser()
    for pub_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for model_dir in sorted(m for m in pub_dir.iterdir() if m.is_dir()):
            manifest = model_dir / "model.yaml"
            if not manifest.is_file():
                continue

            hf_repos = _repos_from_manifest(manifest)
            hf_paths: list[Path] = []
            hf_size = 0
            for user, repo in hf_repos:
                candidate = hf_hub / f"models--{user}--{repo}"
                if candidate.exists():
                    s, _ = size_path(candidate)
                    hf_size += s
                    hf_paths.append(candidate)

            manifest_size, _ = size_path(model_dir)
            total = manifest_size + hf_size
            if total == 0:
                continue

            mid = f"{pub_dir.name}/{model_dir.name}"
            try:
                mtime: float | None = model_dir.lstat().st_mtime
            except OSError:
                mtime = None
            recipe = [f"rm -rf {shlex.quote(str(model_dir))}"]
            # If the real bytes live in HF cache, clean those too — otherwise
            # the user deletes the manifest but keeps the downloaded model.
            for hp in hf_paths:
                recipe.append(f"rm -rf {shlex.quote(str(hp))}")

            entries.append(
                Entry(
                    provider=provider_name,
                    id=f"hub:{mid}",
                    path=model_dir,
                    label=mid,
                    size_bytes=total,
                    mtime=mtime,
                    risk=risk,
                    recipe=recipe,
                    **_stat_kwargs(model_dir),
                )
            )
    return entries


def _repos_from_manifest(manifest: Path) -> list[tuple[str, str]]:
    """Extract (user, repo) pairs from a v0.3+ LM Studio model.yaml."""
    try:
        data: Any = yaml.safe_load(manifest.read_text())
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, str]] = []
    for base in data.get("base") or []:
        if not isinstance(base, dict):
            continue
        for src in base.get("sources") or []:
            if not isinstance(src, dict) or src.get("type") != "huggingface":
                continue
            user = src.get("user")
            repo = src.get("repo")
            if isinstance(user, str) and isinstance(repo, str):
                out.append((user, repo))
    return out
