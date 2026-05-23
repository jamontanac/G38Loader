"""Tests for databases_processing.parse_omim."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from databases_processing.parse_omim import iter_vcf_lines, run


# --------------------------------------------------------------------------
# iter_vcf_lines()
# --------------------------------------------------------------------------

def test_iter_vcf_lines_skips_headers(tmp_path: Path):
    vcf = tmp_path / "test.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        "##INFO=<ID=GENEINFO,Number=1>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672\n"
        "2\t200\t.\tC\tG\t.\t.\tGENEINFO=TP53:7157\n"
    )
    lines = list(iter_vcf_lines(vcf))
    assert len(lines) == 2
    assert lines[0].startswith("1\t100")
    assert lines[1].startswith("2\t200")


def test_iter_vcf_lines_handles_gzip(tmp_path: Path):
    vcf_gz = tmp_path / "test.vcf.gz"
    body = (
        "##fileformat=VCFv4.2\n"
        "1\t100\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672\n"
    )
    with gzip.open(vcf_gz, "wt") as f:
        f.write(body)
    lines = list(iter_vcf_lines(vcf_gz))
    assert len(lines) == 1
    assert "GENEINFO=BRCA1" in lines[0]


# --------------------------------------------------------------------------
# run()
# --------------------------------------------------------------------------

def _vcf(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "clinvar.vcf"
    p.write_text(body)
    return p


def test_run_extracts_unique_gene_omim_pairs(tmp_path: Path):
    vcf = _vcf(tmp_path,
        "##header\n"
        "1\t100\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672;CLNDISDB=OMIM:114480\n"
        "1\t101\t.\tA\tG\t.\t.\tGENEINFO=BRCA1:672;CLNDISDB=OMIM:114480\n"  # dup
        "2\t200\t.\tC\tG\t.\t.\tGENEINFO=TP53:7157;CLNDISDB=OMIM:151623\n"
    )
    out = tmp_path / "out.json"
    run(vcf, out)
    data = json.loads(out.read_text())
    pairs = {(r["Gen"], r["Omim"]) for r in data}
    assert pairs == {("BRCA1", "114480"), ("TP53", "151623")}


def test_run_collects_multiple_omim_per_variant(tmp_path: Path):
    vcf = _vcf(tmp_path,
        "##header\n"
        "1\t100\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672;CLNDISDB=OMIM:114480,OMIM:604370\n"
    )
    out = tmp_path / "out.json"
    run(vcf, out)
    data = json.loads(out.read_text())
    omims = {r["Omim"] for r in data}
    assert omims == {"114480", "604370"}


def test_run_skips_variants_without_geneinfo(tmp_path: Path):
    vcf = _vcf(tmp_path,
        "##header\n"
        "1\t100\t.\tA\tT\t.\t.\tCLNDISDB=OMIM:114480\n"  # no GENEINFO
        "2\t200\t.\tC\tG\t.\t.\tGENEINFO=TP53:7157;CLNDISDB=OMIM:151623\n"
    )
    out = tmp_path / "out.json"
    run(vcf, out)
    data = json.loads(out.read_text())
    assert len(data) == 1
    assert data[0]["Gen"] == "TP53"


def test_run_max_lines_truncates(tmp_path: Path):
    body = "##header\n" + "".join(
        f"1\t{i}\t.\tA\tT\t.\t.\tGENEINFO=G{i}:0;CLNDISDB=OMIM:{i:06d}\n"
        for i in range(10)
    )
    vcf = _vcf(tmp_path, body)
    out = tmp_path / "out.json"
    run(vcf, out, max_lines=3)
    data = json.loads(out.read_text())
    assert len(data) == 3


def test_run_omim_link_format(tmp_path: Path):
    vcf = _vcf(tmp_path,
        "##header\n"
        "1\t100\t.\tA\tT\t.\t.\tGENEINFO=BRCA1:672;CLNDISDB=OMIM:114480\n"
    )
    out = tmp_path / "out.json"
    run(vcf, out)
    rec = json.loads(out.read_text())[0]
    assert rec["enlace_Omim"] == "https://www.omim.org/entry/114480"
