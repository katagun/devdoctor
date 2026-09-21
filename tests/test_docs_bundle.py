"""site/llms-full.txt is docs/*.md concatenated; an edit to one must reach the other."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_llm_docs_bundle_matches_the_docs():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_llms_full.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
