"""Tests for databases_processing.parse_clinvar."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from databases_processing.parse_clinvar import OMIM_RE, run, variant_record


# --------------------------------------------------------------------------
# variant_record()
# --------------------------------------------------------------------------

def _row(**overrides) -> pd.Series:
    base = {
        "RS# (dbSNP)": "1234",
        "OtherIDs": "OMIM:600185",
        "ClinicalSignificance": "Pathogenic",
        "Chromosome": "17",
        "Start": 41245466,
        "ReferenceAlleleVCF": "G",
        "AlternateAlleleVCF": "A",
    }
    base.update(overrides)
    return pd.Series(base)


def test_variant_record_with_rs_and_omim():
    rec = variant_record(_row())
    assert rec["RS_ID"] == "rs1234"
    assert rec["variante"] == "1234"
    assert rec["Enlace_ClinVar"] == "https://www.ncbi.nlm.nih.gov/snp/rs1234/"
    assert rec["Omim"] == "600185"
    assert rec["enlace_Omim"] == "https://www.omim.org/entry/600185"
    assert rec["Clinvar"] == "Pathogenic"
    assert rec["CHROM"] == "17"
    assert rec["POS"] == 41245466
    assert rec["REF"] == "G"
    assert rec["ALT"] == "A"


def test_variant_record_no_rs_id():
    rec = variant_record(_row(**{"RS# (dbSNP)": "-1"}))
    assert rec["RS_ID"] == "NA"
    assert rec["variante"] == "NA"
    assert rec["Enlace_ClinVar"] == "NA"


def test_variant_record_no_omim():
    rec = variant_record(_row(OtherIDs="MedGen:CN169374"))
    assert rec["Omim"] == "NA"
    assert rec["enlace_Omim"] == "NA"


def test_variant_record_omim_with_sub_allele():
    """OMIM:600185.0001 should still match (suffix is optional in OMIM_RE)."""
    rec = variant_record(_row(OtherIDs="OMIM:600185.0001"))
    assert rec["Omim"] == "600185"


def test_variant_record_omim_without_dot_suffix():
    """The original bash extractor required a trailing dot — this one doesn't."""
    rec = variant_record(_row(OtherIDs="something,OMIM:600185,extra"))
    assert rec["Omim"] == "600185"


def test_omim_re_matches_both_forms():
    assert OMIM_RE.search("OMIM:123").group(1) == "123"
    assert OMIM_RE.search("OMIM:123.4").group(1) == "123"


# --------------------------------------------------------------------------
# run()
# --------------------------------------------------------------------------

CLINVAR_TSV_HEADER = (
    "AlleleID\tType\tName\tGeneID\tGeneSymbol\tHGNC_ID\tClinicalSignificance\t"
    "ClinSigSimple\tLastEvaluated\tRS# (dbSNP)\tnsv/esv (dbVar)\tRCVaccession\t"
    "PhenotypeIDS\tPhenotypeList\tOrigin\tOriginSimple\tAssembly\tChromosomeAccession\t"
    "Chromosome\tStart\tStop\tReferenceAllele\tAlternateAllele\tCytogenetic\tReviewStatus\t"
    "NumberSubmitters\tGuidelines\tTestedInGTR\tOtherIDs\tSubmitterCategories\tVariationID\t"
    "PositionVCF\tReferenceAlleleVCF\tAlternateAlleleVCF\tSomaticClinicalImpact\t"
    "SomaticClinicalImpactLastEvaluated\tReviewStatusClinicalImpact\tOncogenicity\t"
    "OncogenicityLastEvaluated\tReviewStatusOncogenicity"
)


def _tsv_row(**vals) -> str:
    """Build a fake variant_summary row from a header-keyed dict."""
    cols = CLINVAR_TSV_HEADER.split("\t")
    out = ["" for _ in cols]
    for k, v in vals.items():
        out[cols.index(k)] = str(v)
    return "\t".join(out)


def test_run_filters_to_grch38_and_writes_json(tmp_path: Path):
    tsv = tmp_path / "vs.txt"
    rows = [
        CLINVAR_TSV_HEADER,
        _tsv_row(**{
            "RS# (dbSNP)": "111", "OtherIDs": "OMIM:111111",
            "ClinicalSignificance": "Pathogenic", "Assembly": "GRCh38",
            "Chromosome": "1", "Start": 100,
            "ReferenceAlleleVCF": "A", "AlternateAlleleVCF": "G",
        }),
        _tsv_row(**{
            "RS# (dbSNP)": "222", "OtherIDs": "OMIM:222222",
            "ClinicalSignificance": "Benign", "Assembly": "GRCh37",
            "Chromosome": "1", "Start": 200,
            "ReferenceAlleleVCF": "C", "AlternateAlleleVCF": "T",
        }),
        _tsv_row(**{
            "RS# (dbSNP)": "333", "OtherIDs": "",
            "ClinicalSignificance": "Uncertain", "Assembly": "GRCh38",
            "Chromosome": "X", "Start": 999,
            "ReferenceAlleleVCF": "T", "AlternateAlleleVCF": "C",
        }),
    ]
    tsv.write_text("\n".join(rows) + "\n")
    out = tmp_path / "out.json"

    run(tsv, out, assembly="GRCh38")

    data = json.loads(out.read_text())
    assert len(data) == 2  # GRCh37 row filtered out
    rs_ids = {r["RS_ID"] for r in data}
    assert rs_ids == {"rs111", "rs333"}
    # GRCh37 row's RS222 is gone
    assert all(r["RS_ID"] != "rs222" for r in data)
