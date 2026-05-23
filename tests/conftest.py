"""Shared fixtures for the test suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fake_config(tmp_path: Path) -> dict:
    """A minimal but complete config dict rooted at tmp_path."""
    return {
        "base_dir": str(tmp_path),
        "reference": {"assembly": "GRCh38"},
        "clinvar": {
            "subdir": "Clinvar",
            "version": "weekly_snapshot",
            "profiles": ["dev", "prod"],
            "estimated_gb": 5,
            "description": "ClinVar test fixture.",
            "variant_summary_url": "http://example.test/vs.txt.gz",
            "vcf_url": "http://example.test/clinvar.vcf.gz",
            "variant_summary_file": "variant_summary.txt",
            "vcf_file": "clinvar.vcf.gz",
            "output_json": "out.json",
        },
        "omim": {
            "subdir": "Omim",
            "version": "derived_from_clinvar",
            "profiles": ["dev", "prod"],
            "estimated_gb": 0,
            "description": "OMIM test fixture.",
            "vcf_file": "clinvar.vcf.gz",
            "output_json": "gene_omim_data.json",
        },
        "equivalences": {
            "ncbi_subdir": "NCBI_gff",
            "refseq_subdir": "RefGene",
            "version": "GRCh38_latest",
            "profiles": ["dev", "prod"],
            "estimated_gb": 2,
            "description": "Equivalences test fixture.",
            "ncbi_gff_url": "http://example.test/ncbi.gff.gz",
            "refseq_lrg_url": "http://example.test/LRG_RefSeqGene",
            "ncbi_gff_file": "ncbi.gff",
            "refseq_lrg_file": "LRG_RefSeqGene.txt",
            "output_json": "eq.json",
        },
        "gnomad": {
            "subdir": "Gnomad/DataVCF",
            "version": "4.1",
            "dataset": "exomes",
            "profiles": ["dev", "prod"],
            "estimated_gb": 200,
            "description": "gnomAD test fixture.",
            "vcf_url_templates": [
                "http://primary.test/v{version}/{chrom}.vcf.bgz",
                "http://fallback.test/v{version}/{chrom}.vcf.bgz",
            ],
            "vcf_filename_template": "gnomad.v{version}.{chrom}.vcf.bgz",
            "chromosomes": ["chr1", "chr2"],
            "output_json_template": "gnomad_AF_{chrom}.json",
        },
        "ensembl": {
            "subdir": "Ensembl",
            "version": "release-112",
            "profiles": ["dev", "prod"],
            "estimated_gb": 0.1,
            "description": "Ensembl test fixture.",
            "regulatory_features_url": "http://example.test/regulatory.gff3.gz",
            "regulatory_features_file": "regulatory.gff3",
        },
        "dbnsfp": {
            "subdir": "dbNSFP",
            "version": "5.0a",
            "profiles": ["prod"],
            "estimated_gb": 200,
            "description": "dbNSFP test fixture.",
            "download_url": "http://example.test/dbnsfp",
            "expected_files": ["dbNSFP5.0a.gz"],
        },
        "spliceai": {
            "subdir": "SpliceAI",
            "version": "raw_hg38",
            "profiles": ["prod"],
            "estimated_gb": 50,
            "description": "SpliceAI test fixture.",
            "download_url": "http://example.test/spliceai",
            "expected_files": [
                "spliceai_scores.raw.snv.hg38.vcf.gz",
                "spliceai_scores.raw.indel.hg38.vcf.gz",
            ],
        },
        "revel": {
            "subdir": "REVEL",
            "version": "1.3",
            "profiles": ["prod"],
            "estimated_gb": 6,
            "description": "REVEL test fixture.",
            "download_url": "http://example.test/revel.zip",
            "download_filename": "revel-v1.3_all_chromosomes.zip",
        },
        "alphamissense": {
            "subdir": "AlphaMissense",
            "version": "hg38",
            "profiles": ["prod"],
            "estimated_gb": 5,
            "description": "AlphaMissense test fixture.",
            "download_url": "http://example.test/alphamissense.tsv.gz",
            "download_filename": "AlphaMissense_hg38.tsv.gz",
        },
        "thousand_genomes": {
            "subdir": "ThousandGenomes",
            "version": "phase3_GRCh38_v2a",
            "profiles": ["prod"],
            "estimated_gb": 60,
            "description": "1000G test fixture.",
            "vcf_url_template": "http://example.test/1000g/chr{chrom}.vcf.gz",
            "vcf_filename_template": "ALL.chr{chrom}.GRCh38.phased.vcf.gz",
            "chromosomes": ["1", "X"],
        },
    }
