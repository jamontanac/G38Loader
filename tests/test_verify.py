"""Tests for g38loader.verify."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from g38loader.provenance import write_readme
from g38loader.verify import (
    parse_readme_files,
    verify_dir,
)


def _write_dataset(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """Lay down some files and a real provenance README. Returns the dir."""
    d = tmp_path / "dataset"
    d.mkdir()
    file_specs = []
    for name, content in files.items():
        p = d / name
        p.write_bytes(content)
        file_specs.append((p, f"http://example.test/{name}"))
    write_readme(
        dataset_name="Test",
        output_dir=d,
        version="v1",
        description="test",
        files=file_specs,
    )
    return d


def test_parse_readme_files_extracts_rows(tmp_path: Path):
    d = _write_dataset(tmp_path, {"a.bin": b"hello", "b.bin": b"world"})
    rows = parse_readme_files(d / "README.md")
    names = {n for n, _ in rows}
    assert names == {"a.bin", "b.bin"}
    digests = {n: s for n, s in rows}
    assert digests["a.bin"] == hashlib.sha256(b"hello").hexdigest()
    assert digests["b.bin"] == hashlib.sha256(b"world").hexdigest()


def test_parse_readme_files_ignores_header_and_separator(tmp_path: Path):
    """Header row (no backticks) and separator row must not be picked up."""
    d = _write_dataset(tmp_path, {"a.bin": b"x"})
    rows = parse_readme_files(d / "README.md")
    assert len(rows) == 1


def test_verify_dir_all_ok(tmp_path: Path):
    d = _write_dataset(tmp_path, {"a.bin": b"hello"})
    ok, mm, missing = verify_dir(d)
    assert (ok, mm, missing) == (1, 0, 0)


def test_verify_dir_detects_mismatch(tmp_path: Path):
    d = _write_dataset(tmp_path, {"a.bin": b"hello"})
    # Tamper with the file after the README is written
    (d / "a.bin").write_bytes(b"tampered")
    ok, mm, missing = verify_dir(d)
    assert (ok, mm, missing) == (0, 1, 0)


def test_verify_dir_detects_missing(tmp_path: Path):
    d = _write_dataset(tmp_path, {"a.bin": b"hello"})
    (d / "a.bin").unlink()
    ok, mm, missing = verify_dir(d)
    assert (ok, mm, missing) == (0, 0, 1)


def test_verify_dir_skips_when_no_readme(tmp_path: Path):
    d = tmp_path / "empty"
    d.mkdir()
    ok, mm, missing = verify_dir(d)
    assert (ok, mm, missing) == (0, 0, 0)


def test_verify_dir_mixed_results(tmp_path: Path):
    d = _write_dataset(tmp_path, {"good.bin": b"a", "bad.bin": b"b", "gone.bin": b"c"})
    (d / "bad.bin").write_bytes(b"changed")
    (d / "gone.bin").unlink()
    ok, mm, missing = verify_dir(d)
    assert (ok, mm, missing) == (1, 1, 1)
