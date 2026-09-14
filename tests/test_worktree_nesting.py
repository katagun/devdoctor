import os

import pytest

from devdoctor.providers._worktree_nesting import check_nesting
from devdoctor.providers._worktree_states import NestedCheck


@pytest.fixture
def worktree(tmp_path):
    root = tmp_path / "wt"
    (root / "src").mkdir(parents=True)
    (root / ".git").write_text("gitdir: /r/.git/worktrees/wt\n")
    return root


def test_the_worktrees_own_git_entry_is_not_nested(worktree):
    assert check_nesting(worktree, [os.path.realpath(worktree)]) == NestedCheck()


def test_a_nested_git_directory_names_its_repository(worktree):
    (worktree / "vendor" / "b" / ".git").mkdir(parents=True)
    (worktree / "vendor" / "a" / ".git").mkdir(parents=True)
    assert check_nesting(worktree, []) == NestedCheck(nested="vendor/a")


def test_a_registered_worktree_inside_is_nested_without_a_git_entry(worktree):
    bare = worktree / "cache" / "mirror.git"
    bare.mkdir(parents=True)
    assert check_nesting(worktree, [os.path.realpath(bare)]) == NestedCheck(
        nested="cache/mirror.git"
    )


def test_a_sibling_sharing_the_name_prefix_is_not_inside(worktree, tmp_path):
    sibling = tmp_path / "wt-2"
    sibling.mkdir()
    assert check_nesting(worktree, [os.path.realpath(sibling)]) == NestedCheck()


def test_symlinks_are_not_followed(worktree, tmp_path):
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    (worktree / "link").symlink_to(other)
    assert check_nesting(worktree, []) == NestedCheck()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_an_unreadable_directory_cannot_be_verified(worktree):
    sealed = worktree / "src" / "sealed"
    sealed.mkdir()
    sealed.chmod(0o000)
    try:
        assert check_nesting(worktree, []) == NestedCheck(unreadable="src/sealed")
    finally:
        sealed.chmod(0o755)


def _repository_shape(directory, parts):
    directory.mkdir(parents=True)
    if "HEAD" in parts:
        (directory / "HEAD").write_text("ref: refs/heads/main\n")
    for name in ("objects", "refs"):
        if name in parts:
            (directory / name).mkdir()


def test_a_directory_git_recognises_as_a_repository_is_nested(worktree):
    _repository_shape(worktree / "vendor" / "mirror.git", {"HEAD", "objects", "refs"})
    assert check_nesting(worktree, []) == NestedCheck(nested="vendor/mirror.git")


@pytest.mark.parametrize(
    "parts",
    [{"HEAD", "objects"}, {"HEAD", "refs"}, {"objects", "refs"}],
    ids=["no-refs", "no-objects", "no-head"],
)
def test_a_directory_with_only_some_repository_parts_is_not_nested(worktree, parts):
    _repository_shape(worktree / "vendor" / "partial", parts)
    assert check_nesting(worktree, []) == NestedCheck()


def test_a_head_directory_is_not_a_repository_head(worktree):
    shape = worktree / "vendor" / "odd"
    (shape / "HEAD").mkdir(parents=True)
    (shape / "objects").mkdir()
    (shape / "refs").mkdir()
    assert check_nesting(worktree, []) == NestedCheck()
