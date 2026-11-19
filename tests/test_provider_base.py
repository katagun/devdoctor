from devdoctor.providers.base import Provider
from devdoctor.types import Entry, Risk
from tests.conftest import FakeShell


class _ClassProvider(Provider):
    name = "cprov"
    description = "test class provider"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "myprog"

    def discover(self) -> list[Entry]:
        return []


def test_available_true_when_platform_matches_and_binary_present(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"myprog": "/usr/local/bin/myprog"})
    assert _ClassProvider(sh).available() is True


def test_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"myprog": None})
    assert _ClassProvider(sh).available() is False


def test_available_false_when_platform_excluded(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    sh = FakeShell(which_table={"myprog": "/x"})
    assert _ClassProvider(sh).available() is False


def test_available_true_when_required_binary_none(monkeypatch):
    class _Pure(Provider):
        name = "pure"
        description = ""
        platforms = ("darwin", "linux")
        risk = Risk.SAFE
        required_binary = None

        def discover(self) -> list[Entry]:
            return []

    monkeypatch.setattr("sys.platform", "linux")
    assert _Pure(FakeShell()).available() is True


def test_no_provider_runs_a_command_without_a_timeout():
    """A hung `conda info` or `xcrun simctl` used to hang the scan, and every
    identical scan waiting on it."""
    import re
    from pathlib import Path

    import devdoctor.providers as providers_pkg

    offenders = []
    for source in sorted(Path(providers_pkg.__file__).parent.glob("*.py")):
        text = source.read_text()
        for match in re.finditer(r"shell\.run\(", text):
            depth, end = 1, match.end()
            while depth and end < len(text):
                depth += {"(": 1, ")": -1}.get(text[end], 0)
                end += 1
            if "timeout=" not in text[match.end() : end]:
                offenders.append(f"{source.name}:{text.count(chr(10), 0, match.start()) + 1}")
    assert offenders == []
