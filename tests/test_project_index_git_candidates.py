import os
from pathlib import Path

import pytest

from devdoctor.providers import project_artifacts
from devdoctor.providers._git import WorktreePointer
from devdoctor.providers.project_artifacts import GitCandidates, ProjectArtifactIndex


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pointer(directory: Path, gitdir: str) -> Path:
    _mkdir(directory)
    (directory / ".git").write_text(f"gitdir: {gitdir}\n")
    return directory


def _git_candidates(root: Path, monkeypatch) -> GitCandidates:
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    return ProjectArtifactIndex().git_candidates()


def test_records_repository_roots(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = _mkdir(root / "repo" / ".git").parent
    assert _git_candidates(root, monkeypatch).repositories == (repo,)


def test_records_a_worktree_pointer_and_derives_its_repository(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    admin = _mkdir(repo / ".git" / "worktrees" / "feature")
    worktree = _pointer(root / "wt" / "feature", str(admin))
    assert _git_candidates(root, monkeypatch).pointers == (
        WorktreePointer(path=worktree, gitdir=admin, repository=repo, broken=False),
    )


def test_resolves_a_relative_gitdir(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    admin = _mkdir(repo / ".git" / "worktrees" / "rel")
    worktree = _pointer(root / "wt" / "rel", "../../repo/.git/worktrees/rel")
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer == WorktreePointer(path=worktree, gitdir=admin, repository=repo, broken=False)


def test_bare_repository_pointer_names_the_bare_directory(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    bare = root / "bare.git"
    admin = _mkdir(bare / "worktrees" / "from-bare")
    _pointer(root / "wt" / "from-bare", str(admin))
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer.repository == bare
    assert pointer.broken is False


def test_pointer_to_a_missing_gitdir_is_broken(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    moved = tmp_path / "moved-away"
    _pointer(root / "wt" / "orphan", str(moved / ".git" / "worktrees" / "orphan"))
    [pointer] = _git_candidates(root, monkeypatch).pointers
    assert pointer.broken is True
    assert pointer.repository == moved


def test_ignores_submodule_and_malformed_git_files(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    _mkdir(root / "super" / ".git" / "modules" / "sub")
    _pointer(root / "super" / "sub", "../.git/modules/sub")
    odd = _mkdir(root / "odd")
    (odd / ".git").write_text("not a pointer\n")
    assert _git_candidates(root, monkeypatch).pointers == ()


def test_records_children_of_worktree_folders(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    repo = root / "repo"
    _mkdir(repo / ".git")
    a = _mkdir(repo / ".worktrees" / "a")
    b = _mkdir(repo / ".worktrees" / "b")
    c = _mkdir(repo / ".claude" / "worktrees" / "c")
    _mkdir(repo / "docs" / "worktrees" / "not-a-worktree-folder")
    assert set(_git_candidates(root, monkeypatch).folder_children) == {a, b, c}


def test_git_candidates_and_artifact_queries_share_one_walk(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(tmp_path / "projects"))
    _mkdir(tmp_path / "projects" / "repo" / ".git")
    calls = []
    original = project_artifacts._index_projects

    def counting():
        calls.append(1)
        return original()

    monkeypatch.setattr(project_artifacts, "_index_projects", counting)
    index = ProjectArtifactIndex()
    index.git_candidates()
    index.candidates("node")
    assert len(calls) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_pointer_into_an_unreadable_directory_is_broken_not_an_error(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    sealed = tmp_path / "sealed" / "repo" / ".git" / "worktrees" / "feature"
    sealed.mkdir(parents=True)
    worktree = _pointer(root / "wt" / "feature", str(sealed))
    sealed_dir = tmp_path / "sealed"
    sealed_dir.chmod(0o000)
    try:
        candidates = _git_candidates(root, monkeypatch)
        [pointer] = candidates.pointers
        assert pointer.path == worktree
        assert pointer.broken is True
    finally:
        sealed_dir.chmod(0o755)


def test_ignores_a_git_file_whose_gitdir_contains_a_nul_byte(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    odd = _mkdir(root / "odd")
    (odd / ".git").write_text("gitdir: /tmp/a\0b/.git/worktrees/x\n")
    assert _git_candidates(root, monkeypatch).pointers == ()
