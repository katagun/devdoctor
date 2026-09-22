"""Rebuild site/llms-full.txt, the single-file rendering of docs/ for LLMs.

    uv run python scripts/build_llms_full.py          # rewrite the bundle
    uv run python scripts/build_llms_full.py --check  # fail if it is out of date

docs/*.md are the source of truth; the bundle is their concatenation in reading
order. ``tests/test_docs_bundle.py`` runs the check, so an edit to docs/ that
forgets the bundle fails the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "site" / "llms-full.txt"
# Reading order: learn it, look things up, then the model behind it.
SOURCES = (
    "docs/tutorial.md",
    "docs/cli-reference.md",
    "docs/web-ui.md",
    "docs/providers.md",
    "docs/safety-model.md",
    "docs/faq.md",
    "docs/agents.md",
)


def render() -> str:
    existing = BUNDLE.read_text()
    header = existing[: existing.index("---\nFile: ")]
    sections = [f"---\nFile: {name}\n---\n\n{_source(name)}\n\n" for name in SOURCES]
    # One trailing newline, which is also what the end-of-file hook enforces.
    return (header + "".join(sections)).rstrip("\n") + "\n"


def _source(name: str) -> str:
    return (ROOT / name).read_text().strip("\n")


def main() -> int:
    rendered = render()
    if "--check" in sys.argv[1:]:
        if BUNDLE.read_text() != rendered:
            print("site/llms-full.txt is out of date; run scripts/build_llms_full.py")
            return 1
        return 0
    BUNDLE.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
