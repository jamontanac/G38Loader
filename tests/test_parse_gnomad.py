"""Tests for g38loader.parse_gnomad."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from g38loader import parse_gnomad as pg


# --------------------------------------------------------------------------
# iter_jobs()
# --------------------------------------------------------------------------

def test_iter_jobs_one_pair_per_chrom(fake_config: dict[str, Any], tmp_path: Path):
    pairs = pg.iter_jobs(fake_config, vcf_dir=tmp_path, output_dir=tmp_path,
                         chroms=["chr1", "chr2"])
    assert len(pairs) == 2


def test_iter_jobs_uses_version_template(fake_config: dict[str, Any], tmp_path: Path):
    """`{version}` and `{chrom}` placeholders are both substituted."""
    pairs = pg.iter_jobs(fake_config, vcf_dir=tmp_path, output_dir=tmp_path,
                         chroms=["chr1"])
    vcf_path, json_path = pairs[0]
    # fake_config has version="4.1", filename template = "gnomad.v{version}.{chrom}.vcf.bgz"
    assert vcf_path.name == "gnomad.v4.1.chr1.vcf.bgz"
    assert json_path.name == "gnomad_AF_chr1.json"


def test_iter_jobs_separates_input_and_output_dirs(fake_config: dict[str, Any], tmp_path: Path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    pairs = pg.iter_jobs(fake_config, vcf_dir=in_dir, output_dir=out_dir,
                         chroms=["chr1"])
    vcf_path, json_path = pairs[0]
    assert vcf_path.parent == in_dir
    assert json_path.parent == out_dir


def test_iter_jobs_empty_chroms_returns_empty(fake_config: dict[str, Any], tmp_path: Path):
    assert pg.iter_jobs(fake_config, vcf_dir=tmp_path, output_dir=tmp_path,
                        chroms=[]) == []


# --------------------------------------------------------------------------
# check_bcftools()
# --------------------------------------------------------------------------

def test_check_bcftools_raises_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pg.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="bcftools"):
        pg.check_bcftools()


def test_check_bcftools_passes_when_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(pg.shutil, "which", lambda _: "/usr/bin/bcftools")
    pg.check_bcftools()  # must not raise


# --------------------------------------------------------------------------
# process_one() — bcftools subprocess mocked
# --------------------------------------------------------------------------

class _FakePopen:
    """Minimal Popen stand-in: __enter__/__exit__, .stdout iterable, .wait()."""

    last_cmd: list[str] | None = None
    output_lines: list[str] = []
    return_code: int = 0

    def __init__(self, cmd, *args, **kwargs):
        type(self).last_cmd = cmd
        self.stdout = iter(self.output_lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait(self):
        return self.return_code


def test_process_one_parses_bcftools_lines(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch):
    vcf = tmp_path / "fake.vcf.bgz"
    vcf.write_bytes(b"placeholder")  # process_one checks file exists
    out = tmp_path / "out.json"

    _FakePopen.output_lines = [
        "chr1\t100\tA\tT\t0.001\n",
        "chr1\t200\tG\tC\t0.05\n",
        "bad-line\n",            # skipped (wrong field count)
        "chr1\t300\tA\tG\tNA\n",  # AF unparseable -> 0.0
    ]
    _FakePopen.return_code = 0
    monkeypatch.setattr(pg.subprocess, "Popen", _FakePopen)

    name, n = pg.process_one(vcf, out)
    assert name == vcf.name
    assert n == 3

    import json
    data = json.loads(out.read_text())
    assert data[0] == {"CHROM": "chr1", "POS": 100, "REF": "A", "ALT": "T", "AF": 0.001}
    assert data[2]["AF"] == 0.0  # NA -> 0


def test_process_one_raises_on_bcftools_failure(tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch):
    vcf = tmp_path / "fake.vcf.bgz"
    vcf.write_bytes(b"x")
    out = tmp_path / "out.json"

    _FakePopen.output_lines = []
    _FakePopen.return_code = 1
    monkeypatch.setattr(pg.subprocess, "Popen", _FakePopen)

    with pytest.raises(Exception):
        pg.process_one(vcf, out)


def test_process_one_missing_input_raises(tmp_path: Path):
    vcf = tmp_path / "missing.vcf.bgz"
    out = tmp_path / "out.json"
    with pytest.raises(FileNotFoundError):
        pg.process_one(vcf, out)
