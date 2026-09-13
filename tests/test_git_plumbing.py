from pathlib import Path

import pytest

from devdoctor.providers._git import (
    MERGE_TREE_MIN_VERSION,
    StatusCounts,
    WorktreeRecord,
    parse_git_version,
    parse_status_porcelain,
    parse_worktree_porcelain,
    supports_merge_tree_write_tree,
)

SHA = "39014f227ec96b48d94c59dd54e6a5dc15566be4"

# Real `git worktree list --porcelain` output (git 2.50.1), fixture path replaced by /fx.
PORCELAIN = (
    "worktree /fx/repo\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /fx/wt/detached\n"
    f"HEAD {SHA}\n"
    "detached\n"
    "\n"
    "worktree /fx/wt/feature branch\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/feature\n"
    "\n"
    "worktree /fx/wt/gone\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/gone\n"
    "prunable gitdir file points to non-existent location\n"
    "\n"
    "worktree /fx/wt/locked-plain\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lp\n"
    "locked\n"
    "\n"
    "worktree /fx/wt/locked-reason\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lr\n"
    "locked agent running\n"
    "\n"
)

# Real porcelain output from a bare repository with one linked worktree.
BARE_PORCELAIN = (
    "worktree /fx/bare.git\n"
    "bare\n"
    "\n"
    "worktree /fx/wt/from-bare\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
)

# Real `git status --porcelain --untracked-files=normal` output.
DIRTY_STATUS = ' M a\nR  b -> b2\nA  c\n M "file name"\n?? notes.txt\n?? scratch/\n'


def test_parse_worktree_porcelain_keeps_git_order_with_primary_first():
    paths = [record.path for record in parse_worktree_porcelain(PORCELAIN)]
    assert paths == [
        Path("/fx/repo"),
        Path("/fx/wt/detached"),
        Path("/fx/wt/feature branch"),
        Path("/fx/wt/gone"),
        Path("/fx/wt/locked-plain"),
        Path("/fx/wt/locked-reason"),
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/fx/repo",
            WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
            id="on-branch",
        ),
        pytest.param(
            "/fx/wt/detached",
            WorktreeRecord(path=Path("/fx/wt/detached"), head=SHA, branch=None, detached=True),
            id="detached",
        ),
        pytest.param(
            "/fx/wt/feature branch",
            WorktreeRecord(path=Path("/fx/wt/feature branch"), head=SHA, branch="feature"),
            id="path-with-space",
        ),
        pytest.param(
            "/fx/wt/gone",
            WorktreeRecord(
                path=Path("/fx/wt/gone"),
                head=SHA,
                branch="gone",
                prunable=True,
                prunable_reason="gitdir file points to non-existent location",
            ),
            id="prunable-with-reason",
        ),
        pytest.param(
            "/fx/wt/locked-plain",
            WorktreeRecord(path=Path("/fx/wt/locked-plain"), head=SHA, branch="lp", locked=True),
            id="locked-without-reason",
        ),
        pytest.param(
            "/fx/wt/locked-reason",
            WorktreeRecord(
                path=Path("/fx/wt/locked-reason"),
                head=SHA,
                branch="lr",
                locked=True,
                lock_reason="agent running",
            ),
            id="locked-with-reason",
        ),
    ],
)
def test_parse_worktree_porcelain_record_shapes(path, expected):
    records = {str(record.path): record for record in parse_worktree_porcelain(PORCELAIN)}
    assert records[path] == expected


def test_parse_worktree_porcelain_bare_record_has_no_head():
    records = parse_worktree_porcelain(BARE_PORCELAIN)
    assert records[0] == WorktreeRecord(
        path=Path("/fx/bare.git"), head=None, branch=None, bare=True
    )
    assert records[1] == WorktreeRecord(path=Path("/fx/wt/from-bare"), head=SHA, branch="main")


def test_parse_worktree_porcelain_ignores_unknown_attributes():
    output = f"worktree /fx/repo\nHEAD {SHA}\nbranch refs/heads/main\nfuture-attribute x\n\n"
    assert parse_worktree_porcelain(output) == [
        WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
    ]


def test_parse_worktree_porcelain_empty_output():
    assert parse_worktree_porcelain("") == []


def test_parse_status_porcelain_counts_tracked_changes_and_untracked_entries():
    counts = parse_status_porcelain(DIRTY_STATUS)
    assert counts == StatusCounts(modified=4, untracked=2)
    assert counts.is_clean is False


def test_parse_status_porcelain_clean_worktree():
    counts = parse_status_porcelain("")
    assert counts == StatusCounts(modified=0, untracked=0)
    assert counts.is_clean is True


def test_parse_status_porcelain_does_not_count_ignored_entries():
    assert parse_status_porcelain("!! node_modules/\n") == StatusCounts(modified=0, untracked=0)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param("git version 2.50.1 (Apple Git-155)\n", (2, 50, 1), id="apple"),
        pytest.param("git version 2.43.0\n", (2, 43, 0), id="linux"),
        pytest.param("git version 2.45.1.windows.1\n", (2, 45, 1), id="windows-suffix"),
        pytest.param("git version 2.39\n", (2, 39, 0), id="no-patch"),
        pytest.param("", None, id="empty"),
        pytest.param("not git at all\n", None, id="garbage"),
    ],
)
def test_parse_git_version(output, expected):
    assert parse_git_version(output) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param(MERGE_TREE_MIN_VERSION, True, id="exactly-minimum"),
        pytest.param((2, 50, 1), True, id="newer"),
        pytest.param((2, 37, 9), False, id="older"),
        pytest.param(None, False, id="unknown"),
    ],
)
def test_supports_merge_tree_write_tree(version, expected):
    assert supports_merge_tree_write_tree(version) is expected
