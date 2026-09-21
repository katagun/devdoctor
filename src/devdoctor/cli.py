from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from devdoctor import cleanup_audit, discovery, registry
from devdoctor import coverage as coverage_mod
from devdoctor import history as history_mod
from devdoctor.cleanup import build_script
from devdoctor.cleanup import run as cleanup_run
from devdoctor.config import load_app_settings
from devdoctor.logging_config import configure_logging
from devdoctor.ports import RealShell, Shell
from devdoctor.providers.base import Provider
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.rendering import (
    CleanupPresenter,
    render_diff_table,
    render_history,
    render_history_run,
    render_report_table,
    spinner,
)
from devdoctor.storage import build_storage
from devdoctor.types import CleanResult, CleanupOpts, Report, Risk, ScanFilters
from devdoctor.units import parse_duration

_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGT]?)$", re.IGNORECASE)
_SIZE_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}
_MIN_SNAPSHOTS_FOR_DIFF = 2


def _open_browser_when_ready(
    health_url: str,
    open_url: str,
    *,
    timeout_s: float = 15.0,
    poll_interval_s: float = 0.1,
) -> None:
    """Open the default browser once the server responds, from a daemon thread.

    Polls `health_url` until it answers (or `timeout_s` elapses, in which case
    it gives up silently). This avoids racing uvicorn's socket bind: opening
    the browser before the server is listening paints a "can't connect" page.
    """
    # Lazy stdlib imports: only the `serve` path needs any of this.
    import contextlib  # noqa: PLC0415
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    import webbrowser  # noqa: PLC0415

    def _poll_then_open() -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=1.0):
                    break
            except Exception:  # best effort; any startup-race error → retry
                # urlopen can raise OSError, HTTPError, or http.client.* errors
                # (e.g. RemoteDisconnected, which is not an OSError) while the
                # server is still binding. Any of them just means "not ready".
                time.sleep(poll_interval_s)
        else:
            return  # server never came up; don't open a broken page
        with contextlib.suppress(Exception):
            webbrowser.open(open_url)

    threading.Thread(target=_poll_then_open, name="devdoctor-open-browser", daemon=True).start()


def _pick_free_port() -> int:
    """Ask the kernel for an unused TCP port on 127.0.0.1.

    We pick the port up-front (rather than letting uvicorn bind port=0) so
    we can build `allowed_hosts` with the concrete port BEFORE uvicorn
    starts — the host-header middleware needs the exact host:port to
    accept requests.
    """
    import socket  # noqa: PLC0415 - stdlib; lazy to keep CLI import lightweight

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _parse_size(s: str) -> int:
    m = _SIZE_RE.match(s)
    if not m:
        raise click.BadParameter(f"invalid size {s!r}; use e.g. 500M, 2G, 100K, or an integer")
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2).upper()])


def _parse_risks(values: tuple[str, ...]) -> frozenset[Risk] | None:
    if not values:
        return None
    flat: list[str] = []
    for v in values:
        flat.extend(v.split(","))
    try:
        return frozenset(Risk(v.strip()) for v in flat if v.strip())
    except ValueError as e:
        raise click.BadParameter(str(e)) from e


def _add_coverage_detail(report: Report, wanted: bool) -> None:
    """Fill in the largest unclassified directories; a walk of the home directory."""
    if wanted and report.coverage is not None:
        report.coverage = coverage_mod.detail(report.coverage, report.entries, Path.home())


def _sort_entries(report: Report, sort_by: str) -> None:
    """Reorder a report in place; a scan arrives sorted by size."""
    if sort_by == "age":
        # Oldest first; an entry of unknown age goes last. The sort is stable, so
        # entries of equal age keep their size order.
        report.entries.sort(key=lambda e: (e.mtime is None, e.mtime or 0.0))


def _parse_older_than(value: str | None) -> float | None:
    """The instant before which an entry must have been last modified, or None."""
    if value is None:
        return None
    try:
        return datetime.now(UTC).timestamp() - parse_duration(value)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="--older-than") from e


_OLDER_THAN_HELP = (
    "Include only entries untouched for at least this long (e.g. 12h, 90d, 2w, 6mo, 1y). "
    "Entries of unknown age are left out."
)


def _parse_providers(values: tuple[str, ...], known: list[Provider]) -> frozenset[str] | None:
    """The provider names a command was limited to; repeatable or comma-separated.

    The names decide which providers run at all (``discovery.scan``), so a typo
    would scan nothing and report nothing. It is a usage error instead.
    """
    names = [name.strip() for value in values for name in value.split(",") if name.strip()]
    if not names:
        return None
    known_names = {provider.name for provider in known}
    unknown = sorted(set(names) - known_names)
    if unknown:
        noun = "provider" if len(unknown) == 1 else "providers"
        raise click.BadParameter(
            f"unknown {noun}: {', '.join(unknown)} (list them with `devdoctor providers`)",
            param_hint="--provider",
        )
    return frozenset(names)


def _free_bytes() -> int | None:
    """Free bytes on the volume holding the home directory; None when unavailable.

    Walks up to the nearest existing ancestor first: a non-existent (but
    otherwise valid) $HOME — as tests pin it, or a fresh account — would
    otherwise make ``disk_usage`` raise even though the volume is readable.
    Note this means a missing $HOME mount can silently report the free space
    of whatever volume holds its nearest existing ancestor (e.g. `/`) instead.
    """
    path = Path.home()
    try:
        while not path.exists():
            path = path.parent
        return shutil.disk_usage(path).free
    except OSError:
        return None


# Selection-phase skip messages (cleanup._resolve_aborted / _to_result) that mean
# "nothing ran": the confirm was declined, or the user quit the per-entry prompts.
_ABORTED_MESSAGES = frozenset({"aborted at confirm", "quit before confirm"})


def _run_outcome(results: list[CleanResult]) -> str:
    """Return "aborted" when the run never reached execution; "ok" otherwise (spec §7).

    A completed run that includes failed entries is still "ok" — that ruling
    stands; only a run with zero ok/error results (nothing executed) and at
    least one confirm-decline/quit message counts as "aborted".
    """
    if any(r.status in ("ok", "error") for r in results):
        return "ok"
    if any(r.message in _ABORTED_MESSAGES for r in results):
        return "aborted"
    return "ok"


def _record_run(
    report: Report,
    presenter: CleanupPresenter,
    results: list[CleanResult],
    free_before: int | None,
    free_after: int | None,
    outcome: str | None = None,
) -> None:
    """Append the run to the audit log the web UI shares; never fails the run."""
    try:
        event = cleanup_audit.build_event(
            results,
            outcome or _run_outcome(results),
            source="cli",
            plan=presenter.plan,
            entries=report.entries,
            free_before=free_before,
            free_after=free_after,
        )
        build_storage(load_app_settings()).append_audit_event(event)
    except Exception:
        logging.getLogger(__name__).warning(
            "cleanup audit write failed; run not recorded", exc_info=True
        )


def _find_run(events: list[dict[str, object]], ref: str) -> dict[str, object] | None:
    if ref.isdigit():
        index = int(ref)
        return events[index - 1] if 1 <= index <= len(events) else None
    return next((e for e in events if e.get("job_id") == ref), None)


def build_cli(shell: Shell | None = None) -> click.Group:  # noqa: PLR0915
    # Many statements because this function wires up every subcommand via
    # nested @cli.command closures; splitting it into modules would hurt
    # readability without reducing complexity.
    sh = shell or RealShell()

    @click.group()
    @click.option(
        "-v",
        "--verbose",
        is_flag=True,
        help="Enable debug logging to stderr (INFO otherwise).",
    )
    @click.pass_context
    def cli(ctx: click.Context, verbose: bool) -> None:
        ctx.ensure_object(dict)
        ctx.obj["shell"] = sh
        configure_logging(verbose)

    @cli.command()
    @click.option("--json", "json_out", is_flag=True, help="Emit Report JSON to stdout.")
    @click.option("--min-size", default=None, help="Filter entries below this size (e.g. 100M).")
    @click.option(
        "--risk",
        "risk",
        multiple=True,
        help="Include only these risks (repeatable or comma-separated).",
    )
    @click.option(
        "--provider",
        "providers",
        multiple=True,
        help="Run only these providers (repeatable or comma-separated).",
    )
    @click.option("--older-than", "older_than", default=None, help=_OLDER_THAN_HELP)
    @click.option(
        "--sort",
        "sort_by",
        type=click.Choice(["size", "age"]),
        default="size",
        show_default=True,
        help="Order entries by size, or by age with the longest untouched first.",
    )
    @click.option(
        "--coverage",
        "with_coverage",
        is_flag=True,
        help=(
            "Also size the home directory outside every classified path and list the "
            "largest directories no provider accounts for. Slow: it walks what the "
            "scan did not."
        ),
    )
    @click.pass_context
    def scan(
        ctx: click.Context,
        json_out: bool,
        min_size: str | None,
        risk: tuple[str, ...],
        providers: tuple[str, ...],
        older_than: str | None,
        sort_by: str,
        with_coverage: bool,
    ) -> None:
        """Find reclaimable space; read-only."""
        providers_list = registry.load_providers(ctx.obj["shell"])
        filters = ScanFilters(
            min_size_bytes=_parse_size(min_size) if min_size else 0,
            risks=_parse_risks(risk),
            providers=_parse_providers(providers, providers_list),
            modified_before=_parse_older_than(older_than),
        )
        if with_coverage and not filters.is_unfiltered:
            raise click.UsageError(
                "--coverage describes the whole scan; drop the filters to use it"
            )
        console = Console()
        if json_out:
            report = discovery.scan(providers_list, filters, datetime.now(UTC))
            _add_coverage_detail(report, with_coverage)
            _sort_entries(report, sort_by)
            click.echo(report.to_json())
            return
        with spinner(console, "Scanning..."):
            report = discovery.scan(providers_list, filters, datetime.now(UTC))
        if with_coverage:
            with spinner(console, "Sizing what no provider accounts for..."):
                _add_coverage_detail(report, with_coverage)
        _sort_entries(report, sort_by)
        render_report_table(console, report)

    @cli.command()
    @click.option(
        "--provider",
        "providers",
        multiple=True,
        help="Run only these providers (repeatable or comma-separated).",
    )
    @click.option(
        "-o",
        "--output",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
    )
    @click.pass_context
    def recipe(
        ctx: click.Context,
        providers: tuple[str, ...],
        output: Path | None,
    ) -> None:
        providers_list = registry.load_providers(ctx.obj["shell"])
        report = discovery.scan(
            providers_list,
            ScanFilters(providers=_parse_providers(providers, providers_list)),
            datetime.now(UTC),
        )
        script = build_script(report)
        if output is None:
            click.echo(script)
        else:
            output.write_text(script)

    @cli.command()
    @click.option(
        "--provider",
        "providers",
        multiple=True,
        help="Run only these providers (repeatable or comma-separated).",
    )
    @click.option(
        "--risk",
        "risk",
        multiple=True,
        help=(
            "Include only these risks (safe, reclaimable, dangerous; "
            "repeatable or comma-separated)."
        ),
    )
    @click.option("--execute", is_flag=True, help="Run the cleanup. Without it, preview only.")
    @click.option(
        "--yes-safe", is_flag=True, help="Approve safe entries without a per-entry prompt."
    )
    @click.option(
        "--yes",
        "yes_all",
        is_flag=True,
        help=(
            "Skip the final confirmation; the plan still prints. "
            "Unattended runs also need --yes-safe."
        ),
    )
    @click.option(
        "--allow-dangerous",
        is_flag=True,
        help="Offer dangerous entries too (they are skipped otherwise).",
    )
    @click.option("--older-than", "older_than", default=None, help=_OLDER_THAN_HELP)
    @click.pass_context
    def clean(
        ctx: click.Context,
        providers: tuple[str, ...],
        risk: tuple[str, ...],
        execute: bool,
        yes_safe: bool,
        yes_all: bool,
        allow_dangerous: bool,
        older_than: str | None,
    ) -> None:
        """Clean up caches found by a scan: preview by default, act with --execute."""
        # Options are checked before the terminal: a typo should read as a typo.
        modified_before = _parse_older_than(older_than)
        if execute and not yes_all and not sys.stdin.isatty():
            raise click.ClickException("no terminal to confirm on; pass --yes to run unattended")
        providers_list = registry.load_providers(ctx.obj["shell"])
        filters = ScanFilters(
            risks=_parse_risks(risk),
            providers=_parse_providers(providers, providers_list),
            modified_before=modified_before,
        )
        console = Console()
        presenter = CleanupPresenter(console)
        with presenter.scanning():
            report = discovery.scan(
                providers_list, filters, datetime.now(UTC), on_progress=presenter.scan_progress
            )
        if not execute:
            render_report_table(console, report)
            console.print("[dim]Preview only — re-run with --execute to perform cleanup.[/]")
            return
        free_before = _free_bytes()
        try:
            with presenter.executing():
                results = cleanup_run(
                    report,
                    shell=ctx.obj["shell"],
                    prompt_choice=presenter.prompt_choice,
                    confirm=(lambda _message: True) if yes_all else presenter.confirm,
                    opts=CleanupOpts(
                        execute=True,
                        yes_safe=yes_safe,
                        allow_dangerous=allow_dangerous,
                        providers=filters.providers,
                    ),
                    # Re-check each worktree immediately before removing it (#110).
                    verify=GitWorktreeProvider(ctx.obj["shell"]).verify_removable,
                    on_event=presenter.on_event,
                )
        except KeyboardInterrupt:
            # A run interrupted mid-flight still gets a summary line and an audit
            # record — silence here is exactly what spec issue #126 complains about.
            free_after = _free_bytes()
            presenter.summary([], free_before=free_before, free_after=free_after)
            _record_run(report, presenter, [], free_before, free_after, outcome="interrupted")
            sys.exit(130)
        free_after = _free_bytes()
        reclaimed_bytes = cleanup_audit.estimated_reclaimed_bytes(report.entries, results)
        presenter.summary(
            results,
            free_before=free_before,
            free_after=free_after,
            reclaimed_bytes=reclaimed_bytes,
        )
        _record_run(report, presenter, results, free_before, free_after)
        if any(r.status == "error" for r in results):
            sys.exit(2)

    @cli.command()
    @click.option("--note", default=None)
    @click.pass_context
    def snapshot(ctx: click.Context, note: str | None) -> None:
        providers_list = registry.load_providers(ctx.obj["shell"])
        console = Console()
        with spinner(console, "Scanning..."):
            report = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
        if note:
            report.note = note
        target = build_storage(load_app_settings()).write_disk_snapshot(report)
        click.echo(f"wrote {target.path}")

    @cli.command()
    @click.option("--from", "from_", default=None, help="Path to earlier snapshot.")
    @click.option("--to", "to_", default=None, help="Path to later snapshot, or 'live'.")
    @click.pass_context
    def diff(ctx: click.Context, from_: str | None, to_: str | None) -> None:
        storage = build_storage(load_app_settings())
        recent = storage.list_disk_snapshots(limit=2, kind=None)
        if from_:
            before_path = Path(from_)
            before = (
                history_mod.load_snapshot(before_path)
                if before_path.is_file()
                else storage.load_disk_snapshot(from_)
            )
        elif len(recent) >= _MIN_SNAPSHOTS_FOR_DIFF:
            before = storage.load_disk_snapshot(recent[-1].name)
        else:
            raise click.UsageError("need at least two snapshots, or pass --from")

        if to_ == "live" or (to_ is None and len(recent) < _MIN_SNAPSHOTS_FOR_DIFF):
            providers_list = registry.load_providers(ctx.obj["shell"])
            after = discovery.scan(providers_list, ScanFilters(), datetime.now(UTC))
        elif to_:
            after_path = Path(to_)
            after = (
                history_mod.load_snapshot(after_path)
                if after_path.is_file()
                else storage.load_disk_snapshot(to_)
            )
        else:
            after = storage.load_disk_snapshot(recent[0].name)

        d = history_mod.diff(before, after)
        render_diff_table(Console(), d)

    @cli.command()
    @click.pass_context
    def providers(ctx: click.Context) -> None:
        providers_list = registry.load_providers(ctx.obj["shell"])
        console = Console()
        table = Table(title="providers")
        table.add_column("Family")
        table.add_column("Name")
        table.add_column("Risk")
        table.add_column("Platforms")
        table.add_column("Available")
        for p in providers_list:
            table.add_row(
                p.family,
                p.name,
                p.risk.value,
                ",".join(p.platforms),
                "yes" if p.available() else "no",
            )
        console.print(table)

    @cli.command()
    @click.argument("ref", required=False)
    @click.option("--limit", default=20, show_default=True, help="Runs to list.")
    @click.option("--json", "json_out", is_flag=True, help="Emit the raw audit events.")
    @click.pass_context
    def history(ctx: click.Context, ref: str | None, limit: int, json_out: bool) -> None:
        """Past cleanup runs: list them, or show one by number (1 = newest) or web job id."""
        del ctx
        events = [
            e
            for e in build_storage(load_app_settings()).read_audit_events(limit=None)
            if e.get("type") == "cleanup"
        ]
        console = Console()
        if ref is None:
            shown = events[:limit]
            if json_out:
                click.echo(json.dumps(shown, indent=2))
                return
            render_history(console, shown)
            return
        run = _find_run(events, ref)
        if run is None:
            raise click.ClickException(f"no cleanup run {ref!r}")
        if json_out:
            click.echo(json.dumps(run, indent=2))
            return
        render_history_run(console, run)

    @cli.command()
    @click.option(
        "--port",
        default=0,
        type=int,
        help="Port to bind (0 = random free port).",
    )
    @click.option(
        "--no-browser",
        is_flag=True,
        help="Do not auto-open the default browser.",
    )
    @click.pass_context
    def serve(ctx: click.Context, port: int, no_browser: bool) -> None:
        """Launch the local web UI."""
        # Imports are intentionally lazy: the `web` extra is optional, so we
        # only import uvicorn and the FastAPI app when `serve` is actually
        # invoked. Without the extra, users get a friendly install hint
        # instead of an ImportError at CLI startup.
        try:
            import uvicorn  # noqa: PLC0415 - lazy: optional `web` extra

            from devdoctor.web.app import build_app  # noqa: PLC0415 - lazy
        except ImportError:
            click.echo(
                "devdoctor serve requires the 'web' extra. Install with:\n"
                "  uv tool install '.[web]' --force",
                err=True,
            )
            ctx.exit(1)
            return

        bind_port = port or _pick_free_port()
        allowed_hosts = {f"127.0.0.1:{bind_port}", f"localhost:{bind_port}"}
        app = build_app(ctx.obj["shell"], allowed_hosts=allowed_hosts)

        url = f"http://127.0.0.1:{bind_port}"
        click.echo(f"DevDoctor web UI -> {url}\nCtrl-C to stop.")

        if not no_browser:
            # Open the browser only once the server actually answers — opening
            # before the bind races uvicorn's startup and paints a "can't
            # connect" page. A daemon thread polls /api/health briefly, then
            # opens (or gives up silently). Swallow every error: headless CI,
            # missing DISPLAY, broken BROWSER env var, Safari AppleScript
            # hiccups — none of these should stop the server from starting.
            _open_browser_when_ready(f"{url}/api/health", url)

        try:
            uvicorn.run(app, host="127.0.0.1", port=bind_port, log_level="info")
        except OSError as exc:
            click.echo(
                f"Could not bind port {bind_port}: {exc}.\nTry --port 0 for a free one.",
                err=True,
            )
            ctx.exit(1)

    return cli


def main() -> None:
    build_cli()(standalone_mode=True)


if __name__ == "__main__":
    main()
