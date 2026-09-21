"""Measure directory sizing: one walk at a time versus the shared walk pool.

Sizing is nearly all of a scan's time (#92), so a change to ``devdoctor.sizer``
or to how providers call it should be measured, not guessed at.

    uv run python scripts/bench_sizer.py                 # synthetic trees in a temp dir
    uv run python scripts/bench_sizer.py ~/projects/a/node_modules ~/projects/b/node_modules

Synthetic trees are small files in nested directories, the shape of
``node_modules``. Real directories give truer numbers; pass the ones a scan of
your machine reports as largest. Totals must match between the two modes: the
pool changes when trees are walked, never what is counted.

To see where a real scan spends its time, read the per-provider timings:

    uv run devdoctor scan --json | python3 -c "import json,sys; \\
      [print(f'{t[\\"duration_ms\\"]/1000:8.1f}s  {t[\\"name\\"]}') for t in \\
       sorted(json.load(sys.stdin)['per_provider'], key=lambda t: -t['duration_ms'])[:10]]"
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from devdoctor import sizer


def _build_tree(root: Path, *, packages: int, files: int) -> None:
    for package in range(packages):
        directory = root / f"pkg-{package}" / "lib" / "dist"
        directory.mkdir(parents=True)
        for index in range(files):
            (directory / f"module-{index}.js").write_bytes(b"x" * 2048)


def _timed(label: str, roots: list[Path], *, pooled: bool) -> int:
    started = time.monotonic()
    if pooled:
        total = sum(result.allocated_bytes for result in sizer.size_many(roots))
    else:
        total = sum(sizer._walk(root).allocated_bytes for root in roots)
    elapsed = time.monotonic() - started
    print(f"{label:<34}{elapsed:8.2f}s   {total / 1e6:10.1f} MB")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("roots", nargs="*", type=Path, help="directories to size")
    parser.add_argument("--trees", type=int, default=16, help="synthetic trees to build")
    parser.add_argument("--packages", type=int, default=150, help="packages per synthetic tree")
    parser.add_argument("--files", type=int, default=20, help="files per package")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="dd-bench-") as scratch:
        roots: list[Path] = list(args.roots)
        if not roots:
            for index in range(args.trees):
                tree = Path(scratch) / f"tree-{index}"
                _build_tree(tree, packages=args.packages, files=args.files)
                roots.append(tree)
        print(f"{len(roots)} trees, pool of {sizer._worker_count()} walks")
        serial = _timed("one walk at a time", roots, pooled=False)
        pooled = _timed("shared walk pool", roots, pooled=True)
        if serial != pooled:
            raise SystemExit(f"totals differ: {serial} != {pooled}")


if __name__ == "__main__":
    main()
