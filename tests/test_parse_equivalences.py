"""Tests for g38loader.parse_equivalences."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from g38loader.parse_equivalences import (
    merge,
    parse_lrg_refseq,
    parse_ncbi_gff,
    run,
)


# --------------------------------------------------------------------------
# parse_ncbi_gff()
# --------------------------------------------------------------------------

def _gff_line(attrs: str) -> str:
    """Build a tab-delimited GFF line where col 9 is the attributes field."""
    return "\t".join(["chr1", "RefSeq", "exon", "1", "100", ".", "+", ".", attrs])


def _write_gff(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "ncbi.gff"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_parse_ncbi_gff_extracts_enst_to_nm(tmp_path: Path):
    p = _write_gff(tmp_path, [
        _gff_line("ID=exon1;Dbxref=Ensembl:ENST00000111111,GenBank:NM_000111"),
        _gff_line("ID=exon2;Dbxref=Ensembl:ENST00000222222,GenBank:NM_000222"),
    ])
    m = parse_ncbi_gff(p)
    assert m == {"ENST00000111111": "NM_000111", "ENST00000222222": "NM_000222"}


def test_parse_ncbi_gff_strips_version_suffix(tmp_path: Path):
    p = _write_gff(tmp_path, [
        _gff_line("Dbxref=Ensembl:ENST00000333333.4,GenBank:NM_000333.7"),
    ])
    m = parse_ncbi_gff(p)
    assert "ENST00000333333" in m
    # GenBank id is kept as-is including version
    assert m["ENST00000333333"] == "NM_000333.7"


def test_parse_ncbi_gff_no_genbank_means_NA(tmp_path: Path):
    p = _write_gff(tmp_path, [
        _gff_line("Dbxref=Ensembl:ENST00000444444"),
    ])
    m = parse_ncbi_gff(p)
    assert m["ENST00000444444"] == "NA"


def test_parse_ncbi_gff_skips_non_enst_ensembl_ids(tmp_path: Path):
    p = _write_gff(tmp_path, [
        _gff_line("Dbxref=Ensembl:ENSG00000555555,GenBank:NM_000555"),
    ])
    m = parse_ncbi_gff(p)
    assert m == {}  # ENSG, not ENST


def test_parse_ncbi_gff_skips_comments_and_short_lines(tmp_path: Path):
    p = _write_gff(tmp_path, [
        "# comment",
        "##gff-version 3",
        "short\tline",  # < 9 cols
        _gff_line("Dbxref=Ensembl:ENST00000666666,GenBank:NM_000666"),
    ])
    m = parse_ncbi_gff(p)
    assert m == {"ENST00000666666": "NM_000666"}


def test_parse_ncbi_gff_skips_lines_without_ensembl(tmp_path: Path):
    p = _write_gff(tmp_path, [
        _gff_line("ID=exon1;Dbxref=GenBank:NM_000777"),  # no Ensembl
        _gff_line("Dbxref=Ensembl:ENST00000888888,GenBank:NM_000888"),
    ])
    m = parse_ncbi_gff(p)
    assert m == {"ENST00000888888": "NM_000888"}


# --------------------------------------------------------------------------
# parse_lrg_refseq()
# --------------------------------------------------------------------------

def _lrg_row(*cols: str) -> str:
    return "\t".join(cols)


def test_parse_lrg_refseq_extracts_nm_to_np(tmp_path: Path):
    p = tmp_path / "lrg.txt"
    p.write_text(
        "# header line\n"
        + _lrg_row("9606", "NG_x", "BRCA1", "NG_005905", "p1", "NM_007294", "v1", "NP_009225") + "\n"
        + _lrg_row("9606", "NG_y", "TP53", "NG_017013",  "p2", "NM_000546", "v1", "NP_000537") + "\n"
    )
    m = parse_lrg_refseq(p)
    assert m == {"NM_007294": "NP_009225", "NM_000546": "NP_000537"}


def test_parse_lrg_refseq_handles_missing_np(tmp_path: Path):
    p = tmp_path / "lrg.txt"
    p.write_text(
        _lrg_row("9606", "NG_x", "GENE1", "NG_001",  "p1", "NM_000001", "v1", "") + "\n"
    )
    m = parse_lrg_refseq(p)
    assert m == {"NM_000001": "NA"}


def test_parse_lrg_refseq_skips_short_rows(tmp_path: Path):
    p = tmp_path / "lrg.txt"
    p.write_text(
        "too\tshort\trow\n"
        + _lrg_row("9606", "NG_x", "GENE", "NG_001", "p", "NM_001", "v", "NP_001") + "\n"
    )
    m = parse_lrg_refseq(p)
    assert m == {"NM_001": "NP_001"}


# --------------------------------------------------------------------------
# merge()
# --------------------------------------------------------------------------

def test_merge_combines_maps():
    enst_to_nm = {"ENST1": "NM_1", "ENST2": "NM_2"}
    nm_to_np = {"NM_1": "NP_1", "NM_2": "NP_2"}
    assert merge(enst_to_nm, nm_to_np) == {
        "ENST1": ["NM_1", "NP_1"],
        "ENST2": ["NM_2", "NP_2"],
    }


def test_merge_uses_NA_when_nm_has_no_np():
    enst_to_nm = {"ENST1": "NM_1"}
    nm_to_np: dict[str, str] = {}
    assert merge(enst_to_nm, nm_to_np) == {"ENST1": ["NM_1", "NA"]}


# --------------------------------------------------------------------------
# run() — end-to-end
# --------------------------------------------------------------------------

def test_run_writes_combined_json(tmp_path: Path):
    gff = _write_gff(tmp_path, [
        _gff_line("Dbxref=Ensembl:ENST00000123.4,GenBank:NM_007294"),
    ])
    lrg = tmp_path / "lrg.txt"
    lrg.write_text(_lrg_row("9606", "x", "BRCA1", "NG_x", "p", "NM_007294", "v", "NP_009225") + "\n")
    out = tmp_path / "eq.json"

    run(gff, lrg, out)
    data = json.loads(out.read_text())
    assert data == {"ENST00000123": ["NM_007294", "NP_009225"]}
