"""End to end: git worktree containment through scan, CLI and web (spec §8.4)."""

import asyncio
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner
from httpx import ASGITransport, AsyncClient

from devdoctor import cleanup, discovery
from devdoctor import cli as cli_module
from devdoctor.cli import build_cli
from devdoctor.ports import RealShell
from devdoctor.providers.git_worktrees import GitWorktreeProvider
from devdoctor.providers.project_artifacts import NodeModulesProvider, ProjectArtifactIndex
from devdoctor.types import CleanupOpts, Refusal, RefusalKind, Risk, ScanFilters
from devdoctor.web.app import build_app


class GitOnlyShell(RealShell):
    """Real subprocesses, but only git counts as installed, so registry scans stay hermetic."""

    def which(self, binary: str) -> str | None:
        return super().which(binary) if binary == "git" else None


@pytest.fixture
def empty_paths_yaml(tmp_path, monkeypatch):
    yaml = tmp_path / "paths.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DEVDOCTOR_PATHS_YAML", str(yaml))


def _integrated_worktree(git_fixture, tmp_path, *, lockfile: bool):
    """A repository with an integrated, clean worktree holding gitignored node_modules."""
    repo = git_fixture.repository(tmp_path / "projects" / "app")
    files = {".gitignore": "node_modules/\n", "package.json": "{}\n"}
    if lockfile:
        files["package-lock.json"] = "{}\n"
    repo.commit("Add package", files)
    worktree = repo.add_worktree(tmp_path / "projects" / "wt" / "feature", "feature")
    worktree.commit("Feature", {"feature.txt": "feature\n"})
    repo.git("merge", "--no-ff", "-q", "-m", "Merge feature", "feature")
    repo.publish()
    package = worktree.path / "node_modules" / "pkg"
    package.mkdir(parents=True)
    (package / "index.js").write_text("x" * 50_000)
    return repo, worktree


@pytest.fixture
def integrated(git_fixture, tmp_path):
    return _integrated_worktree(git_fixture, tmp_path, lockfile=True)


def _scan(filters: ScanFilters | None = None):
    shell = RealShell()
    index = ProjectArtifactIndex()
    providers = [NodeModulesProvider(shell, index=index), GitWorktreeProvider(shell, index=index)]
    return discovery.scan(providers, filters or ScanFilters(), datetime.now(UTC))


def test_contents_of_an_integrated_worktree_are_counted_once(integrated):
    report = _scan()

    [owner] = [e for e in report.entries if e.provider == "git-worktrees"]
    assert owner.risk is Risk.RECLAIMABLE
    assert [e for e in report.entries if e.provider == "node-project-dependencies"] == []
    assert report.total_footprint_bytes() == owner.footprint_bytes
    timings = {timing.name: timing for timing in report.per_provider}
    assert (
        timings["node-project-dependencies"].bytes,
        timings["node-project-dependencies"].entries,
    ) == (0, 0)
    assert sum(timing.bytes for timing in report.per_provider) == owner.size_bytes


def test_a_provider_filter_without_worktrees_contains_nothing(integrated):
    _, worktree = integrated

    report = _scan(ScanFilters(providers=frozenset({"node-project-dependencies"})))

    assert [e.path for e in report.entries] == [worktree.path / "node_modules"]


def test_an_unmeasured_advice_worktree_is_reported(git_fixture, tmp_path):
    repo = git_fixture.repository(tmp_path / "projects" / "app")
    worktree = repo.add_worktree(tmp_path / "projects" / "wt" / "feature", "feature")
    worktree.commit("Unmerged work", {"work.txt": "work\n"})
    repo.publish()

    report = _scan()

    [entry] = [e for e in report.entries if e.provider == "git-worktrees"]
    assert entry.label == "app/feature · not integrated"
    assert entry.is_unmeasured


@pytest.mark.asyncio
async def test_an_id_from_a_dangerous_view_can_start_a_cleanup(
    git_fixture, tmp_path, empty_paths_yaml, monkeypatch
):
    # Without a lockfile, the worktree's node_modules is dangerous; the worktree is not.
    _integrated_worktree(git_fixture, tmp_path, lockfile=False)
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    app = build_app(GitOnlyShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    headers = {"Host": "testserver"}
    registry = app.state.runner_registry
    created = []
    create = registry.create

    def recording_create(factory):
        created.append(create(factory))
        return created[-1]

    monkeypatch.setattr(registry, "create", recording_create)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        full = (await client.get("/api/scan", headers=headers)).json()
        assert "node-project-dependencies" not in {e["provider"] for e in full["entries"]}

        dangerous = (await client.get("/api/scan?risk=dangerous", headers=headers)).json()
        [entry] = [e for e in dangerous["entries"] if e["provider"] == "node-project-dependencies"]

        response = await client.post(
            "/api/clean/jobs", json={"entry_ids": [entry["id"]]}, headers=headers
        )

        assert response.status_code == 200
        # The job may already have finished and left the registry; its report still holds.
        [job] = created
        assert response.json() == {"job_id": job.id}
        assert [e.id for e in job.report.entries] == [entry["id"]]
        active = registry.active()
        if active is not None:
            await active.cancel()


def test_cli_clean_execute_removes_an_integrated_worktree(integrated, empty_paths_yaml):
    repo, worktree = integrated

    result = CliRunner().invoke(build_cli(GitOnlyShell()), ["clean", "--execute"], input="y\ny\n")

    assert result.exit_code == 0, result.output
    assert not worktree.path.exists()
    assert str(worktree.path) not in repo.git("worktree", "list", "--porcelain")


def test_a_worktree_changed_after_the_scan_is_skipped_at_cleanup(integrated):
    _, worktree = integrated
    report = _scan()
    (worktree.path / "late.txt").write_text("written after the scan\n")

    results = cleanup.run(
        report,
        shell=RealShell(),
        prompt_choice=lambda entry: "y",
        confirm=lambda summary: True,
        opts=CleanupOpts(execute=True),
        verify=GitWorktreeProvider(RealShell()).verify_removable,
    )

    [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
    assert result.status == "skipped"
    assert result.message == (
        "changed since the scan: integrated, uncommitted changes; rescan before cleaning"
    )
    assert worktree.path.exists()


def test_git_still_refuses_a_worktree_dirtied_after_verification(integrated):
    """Second line of defence (#110 final review): git's own check still guards removal.

    Re-verification only catches a change up to the moment it runs; a change landing
    between the verifier's answer and the `git worktree remove` call is still caught by
    git itself, which refuses to remove a worktree holding untracked or modified files.
    This should already pass on prior code — it documents that guarantee, it does not
    add one.
    """
    _, worktree = integrated
    report = _scan()

    def verify(entry):
        if entry.provider != "git-worktrees":
            return Refusal(RefusalKind.UNVERIFIED, "only worktrees are verified")
        (worktree.path / "late.txt").write_text("written after verification\n")
        return None  # accept, then let git's own check refuse the removal

    results = cleanup.run(
        report,
        shell=RealShell(),
        prompt_choice=lambda entry: "y",
        confirm=lambda summary: True,
        opts=CleanupOpts(execute=True),
        verify=verify,
    )

    [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
    assert result.status == "error"
    assert "untracked" in result.message
    assert worktree.path.exists()


def _detached_integrated(git_fixture, tmp_path):
    """An integrated, clean worktree on a detached HEAD, as agent tooling creates them."""
    repo = git_fixture.repository(tmp_path / "projects" / "app")
    worktree = repo.add_detached_worktree(tmp_path / "projects" / "wt" / "agent")
    repo.publish()
    return repo, worktree


def test_cli_clean_skips_a_worktree_committed_to_while_the_prompt_waits(
    git_fixture, tmp_path, empty_paths_yaml, monkeypatch
):
    repo, worktree = _detached_integrated(git_fixture, tmp_path)
    late: list[str] = []
    results = []

    def prompt_choice(entry):
        # The race #110 is about: work is committed after the scan, before removal.
        late.append(worktree.commit("Late work", {"late.txt": "late\n"}))
        return "y"

    def recording_run(*args, **kwargs):
        results.extend(cleanup.run(*args, **kwargs))
        return results

    monkeypatch.setattr(cli_module, "real_prompts", lambda console: (prompt_choice, lambda s: True))
    monkeypatch.setattr(cli_module, "cleanup_run", recording_run)

    outcome = CliRunner().invoke(build_cli(GitOnlyShell()), ["clean", "--execute"])

    assert outcome.exit_code == 0, outcome.output
    [result] = [r for r in results if r.entry_id.startswith("git-worktrees:")]
    assert result.status == "skipped"
    assert result.message == "changed since the scan: not integrated; rescan before cleaning"
    assert worktree.path.exists()
    assert repo.git("cat-file", "-t", late[0]) == "commit"


async def test_web_cleanup_skips_a_worktree_committed_to_before_confirmation(
    git_fixture, tmp_path, empty_paths_yaml, monkeypatch
):
    repo, worktree = _detached_integrated(git_fixture, tmp_path)
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    app = build_app(GitOnlyShell(), allowed_hosts={"testserver"}, static_dir=tmp_path)
    headers = {"Host": "testserver"}
    registry = app.state.runner_registry
    created = []
    create = registry.create

    def recording_create(factory):
        created.append(create(factory))
        return created[-1]

    monkeypatch.setattr(registry, "create", recording_create)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        scan = (await client.get("/api/scan", headers=headers)).json()
        [entry] = [e for e in scan["entries"] if e["provider"] == "git-worktrees"]
        assert entry["risk"] == "reclaimable"

        response = await client.post(
            "/api/clean/jobs", json={"entry_ids": [entry["id"]]}, headers=headers
        )
        assert response.status_code == 200
        [job] = created

        event = await asyncio.wait_for(job.events.get(), timeout=10)
        assert event["event"] == "prompt"
        await job.answer_prompt(entry_id=entry["id"], choice="y")
        event = await asyncio.wait_for(job.events.get(), timeout=10)
        assert event["event"] == "awaiting_confirm"

        late = worktree.commit("Late work", {"late.txt": "late\n"})
        await job.answer_confirm(True)

        while event["event"] != "done":
            event = await asyncio.wait_for(job.events.get(), timeout=30)

    [result] = [r for r in event["data"]["results"] if r["entry_id"] == entry["id"]]
    assert result["status"] == "skipped"
    assert result["message"] == "changed since the scan: not integrated; rescan before cleaning"
    assert worktree.path.exists()
    assert repo.git("cat-file", "-t", late) == "commit"
