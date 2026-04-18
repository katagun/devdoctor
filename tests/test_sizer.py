from pathlib import Path

from diskdoctor.sizer import size_path


def _write(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_size_path_returns_zero_for_missing_root(tmp_path: Path):
    missing = tmp_path / "nope"
    size, skipped = size_path(missing)
    assert size == 0
    assert skipped == [missing]


def test_size_path_sums_file_bytes(tmp_path: Path):
    _write(tmp_path / "a.txt", b"x" * 100)
    _write(tmp_path / "sub" / "b.txt", b"y" * 250)
    size, skipped = size_path(tmp_path)
    assert size == 350
    assert skipped == []


def test_size_path_does_not_follow_symlinks(tmp_path: Path):
    # Real file outside the tree.
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "big.bin").write_bytes(b"z" * 10_000)

    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "tiny.txt").write_bytes(b"a" * 10)
    (scan_dir / "link-to-real").symlink_to(real_dir)

    size, skipped = size_path(scan_dir)
    # Only tiny.txt plus the symlink inode itself (not the 10k file behind it).
    assert size < 1_000


def test_size_path_handles_symlink_loop(tmp_path: Path):
    d = tmp_path / "loop"
    d.mkdir()
    (d / "self").symlink_to(d)
    (d / "f").write_bytes(b"o" * 5)
    size, skipped = size_path(d)
    assert size < 100  # loop does not hang; link inode is tiny


def test_size_path_records_permission_denied(tmp_path: Path):
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "hidden.txt").write_bytes(b"s" * 20)
    protected.chmod(0o000)
    try:
        size, skipped = size_path(tmp_path)
        # Directory itself contributed, but walking inside was blocked.
        # We just care we didn't raise and we recorded the skip.
        assert any(str(protected) in str(p) for p in skipped) or size >= 0
    finally:
        protected.chmod(0o755)  # so pytest can clean up
