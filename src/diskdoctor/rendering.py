from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from rich.console import Console
from rich.prompt import Confirm as RichConfirm
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from diskdoctor.types import Choice, Confirm, DiffReport, Entry, PromptChoice, Report, Risk

# Every C0 control char (incl. ESC 0x1b and newline) plus DEL. Rich's own
# strip_control_codes intentionally keeps ESC, so we drop these ourselves.
_CONTROL_STRIP = {c: None for c in [*range(0x20), 0x7F]}


def _strip_controls(value: str) -> str:
    return value.translate(_CONTROL_STRIP)


def _safe_cell(value: str) -> Text:
    """Render a filename-derived string as inert text.

    Entry labels, provider names, and recipe hints come from attacker-nameable
    files/dirs. Passed as a plain string, Rich would parse ``[...]`` as markup
    (a malformed tag raises MarkupError and aborts the whole render) and would
    pass raw ANSI/OSC escapes straight to the terminal (screen-clear, title
    spoofing, output forgery). ``Text`` disables markup; stripping control
    chars (ESC included) removes the escape sequences.
    """
    return Text(_strip_controls(value))


def render_report_table(console: Console, report: Report) -> None:
    table = Table(title=f"diskdoctor scan — {len(report.entries)} entries", show_lines=False)
    table.add_column("Provider", style="cyan")
    table.add_column("Label", overflow="fold")
    table.add_column("Size", justify="right")
    table.add_column("Risk", justify="center")
    table.add_column("Stale?", justify="center")
    table.add_column("Recipe hint", overflow="ellipsis")

    term_width = shutil.get_terminal_size((120, 24)).columns
    hint_max = max(20, term_width - 80)

    for e in report.entries:
        table.add_row(
            _safe_cell(e.provider),
            _safe_cell(e.label),
            _human_bytes(e.size_bytes),
            _risk_label(e.risk),
            _staleness(e.mtime),
            _safe_cell((e.recipe[0] if e.recipe else "")[:hint_max]),
        )

    if not report.entries:
        table.add_row("(no entries)", "", "", "", "", "")

    table.caption = f"Total: {_human_bytes(report.total_bytes())}"
    console.print(table)


def render_diff_table(console: Console, diff: DiffReport) -> None:
    table = Table(
        title=f"diff: {diff.before_at.isoformat()} → {diff.after_at.isoformat()}",
    )
    table.add_column("Provider", style="cyan")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Δ bytes", justify="right")
    table.add_column("Δ %", justify="right")

    for r in diff.rows:
        color = "green" if r.delta_bytes < 0 else ("red" if r.delta_bytes > 0 else "")
        style = f"[{color}]" if color else ""
        end = "[/]" if color else ""
        table.add_row(
            r.provider,
            _human_bytes(r.before_bytes),
            _human_bytes(r.after_bytes),
            f"{style}{r.delta_bytes:+d}{end}",
            f"{style}{r.delta_pct:+.1f}%{end}",
        )

    console.print(table)


def real_prompts(console: Console) -> tuple[PromptChoice, Confirm]:
    """Build the real Rich-backed prompt callables."""

    def prompt_choice(entry: Entry) -> Choice:
        header = Text()
        header.append(_strip_controls(entry.provider), style="bold")
        header.append(
            f" — {_strip_controls(entry.label)}  "
            f"({_human_bytes(entry.size_bytes)}, risk={_risk_label(entry.risk)})"
        )
        console.print(header)
        recipe_hint = _strip_controls(entry.recipe[0]) if entry.recipe else "(no recipe)"
        console.print(Text(f"  → {recipe_hint}"))
        raw = Prompt.ask(
            "[y]es / [n]o / [a]ll-in-provider / [s]kip-provider / [q]uit",
            console=console,
            choices=["y", "n", "a", "s", "q"],
            default="n",
            show_choices=False,
        )
        return raw  # type: ignore[return-value]

    def confirm(message: str) -> bool:
        return RichConfirm.ask(message, console=console, default=False)

    return prompt_choice, confirm


@contextmanager
def spinner(console: Console, message: str) -> Iterator[None]:
    with console.status(message):
        yield


def _risk_label(risk: Risk) -> str:
    return {
        Risk.SAFE: "safe",
        Risk.RECLAIMABLE: "reclaim",
        Risk.DANGEROUS: "DANGER",
    }[risk]


_BYTES_UNIT_STEP = 1024
_DAYS_PER_MONTH = 30
_DAYS_PER_YEAR = 365


def _human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    value: float = float(abs(n))
    for unit in ("B", "K", "M", "G", "T", "P"):
        if value < _BYTES_UNIT_STEP or unit == "P":
            return f"{sign}{value:.0f}{unit}" if unit == "B" else f"{sign}{value:.1f}{unit}"
        value /= _BYTES_UNIT_STEP
    return f"{sign}{value:.1f}P"


def _staleness(mtime: float | None) -> str:
    if mtime is None:
        return "—"
    age_days = (datetime.now().timestamp() - mtime) / 86400
    if age_days < 1:
        return "today"
    if age_days < _DAYS_PER_MONTH:
        return f"{int(age_days)}d"
    if age_days < _DAYS_PER_YEAR:
        return f"{int(age_days / _DAYS_PER_MONTH)}mo"
    return f"{age_days / _DAYS_PER_YEAR:.1f}y"
