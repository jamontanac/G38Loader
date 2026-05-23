"""Tests for databases_processing.provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from databases_processing.provenance import (
    human_size,
    sha256_file,
    write_readme,
)


def test_human_size_units():
    assert human_size(0) == "0.0 B"
    assert human_size(512) == "512.0 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1024 * 1024) == "1.0 MB"
    assert human_size(2 * 1024**3) == "2.0 GB"


def test_sha256_file_matches_hashlib(tmp_path: Path):
    target = tmp_path / "blob.bin"
    payload = b"hello world\n" * 1024
    target.write_bytes(payload)
    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_sha256_file_chunked_streaming(tmp_path: Path):
    # 5 MB -> exercises >1 chunk read in sha256_file
    target = tmp_path / "big.bin"
    target.write_bytes(b"x" * (5 * 1024 * 1024))
    expected = hashlib.sha256(b"x" * (5 * 1024 * 1024)).hexdigest()
    assert sha256_file(target) == expected


def test_write_readme_happy_path(tmp_path: Path):
    f1 = tmp_path / "data.txt"
    f1.write_bytes(b"hi")
    f2 = tmp_path / "data.vcf.gz"
    f2.write_bytes(b"\x1f\x8b\x08placeholder")

    out = write_readme(
        dataset_name="ClinVar",
        output_dir=tmp_path,
        version="weekly_snapshot",
        description="Test dataset.",
        assembly="GRCh38",
        files=[
            (f1, "http://example.test/data.txt"),
            (f2, "http://example.test/data.vcf.gz"),
        ],
    )
    assert out == tmp_path / "README.md"
    body = out.read_text()
    assert "# ClinVar" in body
    assert "Version:      weekly_snapshot" in body
    assert "Assembly:     GRCh38" in body
    assert "`data.txt`" in body
    assert "http://example.test/data.txt" in body
    # SHA256 cell present (a row containing both filename and a 64-hex digest)
    assert hashlib.sha256(b"hi").hexdigest() in body
    assert "Test dataset." in body


def test_write_readme_skips_missing_files(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    real = tmp_path / "real.bin"
    real.write_bytes(b"x")
    missing = tmp_path / "ghost.bin"

    write_readme(
        dataset_name="Equivalences",
        output_dir=tmp_path,
        version="GRCh38_latest",
        description="Test.",
        files=[(real, "http://example.test/real"), (missing, "http://example.test/ghost")],
    )
    body = (tmp_path / "README.md").read_text()
    assert "real.bin" in body
    assert "ghost.bin" not in body


def test_write_readme_extra_metadata(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"x")
    write_readme(
        dataset_name="gnomAD exomes",
        output_dir=tmp_path,
        version="4.1",
        description="test",
        files=[(f, "http://example.test/x")],
        extra_metadata={"Dataset": "exomes"},
    )
    body = (tmp_path / "README.md").read_text()
    assert "Dataset: exomes" in body


def test_write_readme_atomic_no_part_left(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"x")
    write_readme(
        dataset_name="X",
        output_dir=tmp_path,
        version="v1",
        description="t",
        files=[(f, "u")],
    )
    assert not (tmp_path / "README.md.part").exists()
