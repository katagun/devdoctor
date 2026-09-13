from pathlib import Path

import pytest

from devdoctor.providers._git import StatusCounts
from devdoctor.providers._worktree_states import (
    Integration,
    WorktreeFacts,
    WorktreeState,
    advice_message,
    classify,
    worktree_label,
)

CLEAN = StatusCounts(modified=0, untracked=0)
DIRTY = StatusCounts(modified=7, untracked=3)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        pytest.param(
            WorktreeFacts(toplevel_ok=False, locked=True, default_branch=None),
            WorktreeState.BROKEN_POINTER,
            id="broken-pointer-wins-over-everything",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=False, locked=True, default_branch=None, failure="timed out after 30 s"
            ),
            WorktreeState.GIT_ERROR,
            id="unverified-ownership-git-error-wins-over-locked",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=True, default_branch=None),
            WorktreeState.LOCKED,
            id="locked-wins-over-no-default-branch",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=False, default_branch=None, failure="boom"),
            WorktreeState.NO_DEFAULT_BRANCH,
            id="no-default-branch-wins-over-git-error",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                failure="timed out after 30 s",
                integration=Integration.NOT_INTEGRATED,
            ),
            WorktreeState.GIT_ERROR,
            id="git-error-wins-over-not-integrated",
        ),
        pytest.param(
            WorktreeFacts(toplevel_ok=True, locked=False, default_branch="origin/main"),
            None,
            id="integration-still-needed",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.NOT_INTEGRATED,
                status=DIRTY,
            ),
            WorktreeState.NOT_INTEGRATED,
            id="not-integrated-ignores-status",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
            ),
            None,
            id="status-still-needed",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
                status=DIRTY,
            ),
            WorktreeState.DIRTY,
            id="integrated-but-dirty",
        ),
        pytest.param(
            WorktreeFacts(
                toplevel_ok=True,
                locked=False,
                default_branch="origin/main",
                integration=Integration.INTEGRATED,
                status=CLEAN,
            ),
            WorktreeState.INTEGRATED,
            id="integrated-and-clean",
        ),
    ],
)
def test_classify_returns_the_first_matching_state(facts, expected):
    assert classify(facts) is expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param(
            {"branch": "table-footers", "directory": Path("/r/.worktrees/table-footers")},
            "indexcat/table-footers · integrated",
            id="branch-matches-directory",
        ),
        pytest.param(
            {"branch": "fix/api-keys", "directory": Path("/r/wt/practical-feistel")},
            "indexcat/practical-feistel · fix/api-keys · integrated",
            id="branch-differs-from-directory",
        ),
        pytest.param(
            {"detached": True, "head": "e317178606aa", "directory": Path("/c/amj")},
            "indexcat/amj · detached @e317178 · integrated",
            id="detached-head",
        ),
    ],
)
def test_worktree_label(kwargs, expected):
    assert (
        worktree_label(repository_name="indexcat", state=WorktreeState.INTEGRATED, **kwargs)
        == expected
    )


def test_state_values_are_the_label_texts_from_the_spec():
    assert [state.value for state in WorktreeState] == [
        "integrated",
        "integrated, uncommitted changes",
        "not integrated",
        "broken pointer",
        "locked",
        "no default branch",
        "git error",
        "unverifiable",
    ]


REPO = Path("/p/indexcat")


@pytest.mark.parametrize(
    ("state", "kwargs", "expected"),
    [
        pytest.param(
            WorktreeState.BROKEN_POINTER,
            {"gitdir": Path("/old/indexcat/.git/worktrees/amj")},
            "This worktree's .git file points to /old/indexcat/.git/worktrees/amj, which does "
            'not exist; the repository was probably moved. Run "git -C /p/indexcat worktree '
            'repair", then rescan.',
            id="broken-pointer",
        ),
        pytest.param(
            WorktreeState.BROKEN_POINTER,
            {},
            "This worktree's .git does not point back to /p/indexcat. Run "
            '"git -C /p/indexcat worktree repair", then rescan.',
            id="broken-pointer-not-pointing-back",
        ),
        pytest.param(
            WorktreeState.LOCKED,
            {"lock_reason": "agent running"},
            "Locked by git: agent running.",
            id="locked-with-reason",
        ),
        pytest.param(WorktreeState.LOCKED, {}, "Locked by git.", id="locked-without-reason"),
        pytest.param(
            WorktreeState.NO_DEFAULT_BRANCH,
            {},
            "Cannot determine the default branch of /p/indexcat: no origin/HEAD, origin/main "
            "or origin/master.",
            id="no-default-branch",
        ),
        pytest.param(
            WorktreeState.GIT_ERROR,
            {"failure": "timed out after 30 s"},
            "git failed while checking this worktree: timed out after 30 s.",
            id="git-error",
        ),
        pytest.param(
            WorktreeState.NOT_INTEGRATED,
            {"default_branch": "origin/main"},
            "Not integrated into origin/main. Anything inside it that other providers report "
            "can still be cleaned individually.",
            id="not-integrated",
        ),
        pytest.param(
            WorktreeState.DIRTY,
            {"default_branch": "origin/main", "status": DIRTY},
            "Integrated into origin/main, but has 7 modified and 3 untracked files. Commit, "
            "stash or discard them first.",
            id="integrated-dirty",
        ),
        pytest.param(
            WorktreeState.UNVERIFIABLE,
            {},
            "Inside a worktree folder, but not a registered git worktree. DevDoctor cannot "
            "verify what it contains.",
            id="unverifiable",
        ),
    ],
)
def test_advice_messages_match_the_spec(state, kwargs, expected):
    assert advice_message(state, repository=REPO, **kwargs) == expected


def test_integrated_has_no_advice():
    with pytest.raises(ValueError, match="not an advice state"):
        advice_message(WorktreeState.INTEGRATED, repository=REPO)
