from pathlib import Path

import pytest

from devdoctor.containment import contain_worktree_contents, path_is_inside
from devdoctor.types import DiskUsage, Entry, Risk, ScanFilters

ALL = ScanFilters()


def _entry(provider: str, path: Path | None, *, risk=Risk.RECLAIMABLE, size=100) -> Entry:
    usage = DiskUsage(None, None) if size == 0 else DiskUsage(size, size)
    return Entry(
        provider=provider,
        id=f"{provider}:{path}",
        path=path,
        label=str(path),
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=[],
        usage=usage,
    )


def _worktree(path: Path, *, risk=Risk.RECLAIMABLE) -> Entry:
    return _entry("git-worktrees", path, risk=risk, size=0 if risk is Risk.DANGEROUS else 500)


def _ids(entries):
    return [e.id for e in entries]


WT = Path("/p/app/.worktrees/feature")


def test_contents_of_a_reclaimable_worktree_are_removed():
    owner = _worktree(WT)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    same_path = _entry("tox-nox-environments", WT)
    outside = _entry("node-project-dependencies", Path("/p/app/node_modules"))
    result = contain_worktree_contents([owner, inside, same_path, outside], ALL)
    assert _ids(result) == [owner.id, outside.id]


def test_a_sibling_sharing_the_name_prefix_is_not_contained():
    owner = _worktree(WT)
    sibling = _entry("node-project-dependencies", Path("/p/app/.worktrees/feature-2/node_modules"))
    assert _ids(contain_worktree_contents([owner, sibling], ALL)) == [owner.id, sibling.id]


def test_advice_worktrees_contain_nothing():
    owner = _worktree(WT, risk=Risk.DANGEROUS)
    inside = _entry("node-project-dependencies", WT / "node_modules")
    assert _ids(contain_worktree_contents([owner, inside], ALL)) == [owner.id, inside.id]


@pytest.mark.parametrize(
    "filters",
    [
        pytest.param(ScanFilters(risks=frozenset({Risk.DANGEROUS})), id="risk-filter"),
        pytest.param(ScanFilters(min_size_bytes=10_000), id="min-size"),
        pytest.param(
            ScanFilters(providers=frozenset({"node-project-dependencies"})), id="provider"
        ),
        pytest.param(ScanFilters(modified_before=1.0), id="age"),
    ],
)
def test_an_owner_outside_the_view_contains_nothing(filters):
    owner = _worktree(WT)
    inside = _entry("node-project-dependencies", WT / "node_modules", risk=Risk.DANGEROUS)
    assert _ids(contain_worktree_contents([owner, inside], filters)) == [owner.id, inside.id]


def test_entries_without_a_path_are_never_contained():
    owner = _worktree(WT)
    logical = _entry("docker", None)
    assert _ids(contain_worktree_contents([owner, logical], ALL)) == [owner.id, logical.id]


def test_worktree_entries_are_never_contained_by_another_worktree():
    outer = _worktree(Path("/p/app"))
    nested = _worktree(Path("/p/app/.worktrees/feature"))
    assert _ids(contain_worktree_contents([outer, nested], ALL)) == [outer.id, nested.id]


def test_paths_are_compared_after_resolving_symlinks(tmp_path):
    real = tmp_path / "real" / "feature"
    (real / "node_modules").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    owner = _worktree(link / "feature")
    inside = _entry("node-project-dependencies", real / "node_modules")
    assert _ids(contain_worktree_contents([owner, inside], ALL)) == [owner.id]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("/p/app/.worktrees/feature", True, id="equal"),
        pytest.param("/p/app/.worktrees/feature/web/node_modules", True, id="inside"),
        pytest.param("/p/app/.worktrees/feature-2", False, id="sibling-sharing-the-prefix"),
        pytest.param("/p/app", False, id="parent"),
    ],
)
def test_path_is_inside(path, expected):
    assert path_is_inside(path, {str(WT)}) is expected
