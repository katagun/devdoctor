from __future__ import annotations

from dataclasses import dataclass, field

from diskdoctor.types import ShellResult


@dataclass
class FakeShell:
    """Argv-keyed fake. Matches full argv tuple exactly.

    Unconfigured calls raise so tests surface unexpected commands.
    """

    responses: dict[tuple[str, ...], ShellResult] = field(default_factory=dict)
    which_table: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> ShellResult:
        # `check` and `timeout` are accepted for Protocol conformance but
        # not enforced by the fake — tests configure their responses explicitly.
        del check, timeout
        key = tuple(argv)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"FakeShell: unexpected call: {argv}")
        return self.responses[key]

    def which(self, binary: str) -> str | None:
        return self.which_table.get(binary)
