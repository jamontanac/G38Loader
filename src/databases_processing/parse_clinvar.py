"""Parse ClinVar's variant_summary.txt into a JSON list of variants.

Reads the tab-delimited variant_summary dump and emits one JSON record per
variant with the fields used downstream (RS ID, ClinVar significance, OMIM,
genomic coordinates, links).

Filters to GRCh38 rows so we don't double-count GRCh37/GRCh38 entries.

Usage:
    python parse_clinvar.py \\
        --input /datadrive/Databases/Clinvar/variant_summary.txt \\
        --output /datadrive/Databases/Clinvar/variantes_clinvar.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from databases_processing.common import load_config, db_path, setup_logging

log = logging.getLogger("parse_clinvar")

# Match OMIM:<digits> with an optional .<sub-allele> suffix
# Original script required the trailing dot, which dropped some entries.
OMIM_RE = re.compile(r"OMIM:(\d+)(?:\.\d+)?")


def variant_record(row: pd.Series) -> dict[str, Any]:
    """Convert one variant_summary row into the standardized dict."""
    rs_raw = str(row["RS# (dbSNP)"])
    other_ids = str(row.get("OtherIDs", "") or "")

    # ClinVar uses -1 to mean "no dbSNP rs"
    if rs_raw in ("-1", "nan", ""):
        rs_id = "NA"
        variante = "NA"
        enlace_clinvar = "NA"
    else:
        rs_id = f"rs{rs_raw}"
        variante = rs_raw
        enlace_clinvar = f"https://www.ncbi.nlm.nih.gov/snp/{rs_id}/"

    match = OMIM_RE.search(other_ids)
    if match:
        omim = match.group(1)
        enlace_omim = f"https://www.omim.org/entry/{omim}"
    else:
        omim = "NA"
        enlace_omim = "NA"

    return {
        "variante": variante,
        "RS_ID": rs_id,
        "Clinvar": row["ClinicalSignificance"],
        "Enlace_ClinVar": enlace_clinvar,
        "CHROM": row["Chromosome"],
        "POS": row["Start"],
        "REF": row["ReferenceAlleleVCF"],
        "ALT": row["AlternateAlleleVCF"],
        "Omim": omim,
        "enlace_Omim": enlace_omim,
    }


def run(input_file: Path, output_file: Path, assembly: str = "GRCh38") -> None:
    log.info("Reading variant_summary from %s", input_file)
    df = pd.read_csv(input_file, sep="\t", low_memory=False)
    log.info("Loaded %d rows", len(df))

    if "Assembly" in df.columns:
        before = len(df)
        df = df[df["Assembly"] == assembly]
        log.info("Filtered to %s: %d -> %d rows", assembly, before, len(df))

    log.info("Building variant records...")
    records = [variant_record(row) for _, row in df.iterrows()]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    log.info("Writing %d records to %s", len(records), output_file)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=4)
    log.info("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--config", type=Path, default=None,
                        help="Path to config.yaml (defaults to ../config/config.yaml)")
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--input", type=Path, default=None,
                        help="Override input variant_summary.txt path")
    parser.add_argument("--output", type=Path, default=None,
                        help="Override output JSON path")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load_config(args.config, base_dir=args.base_dir)

    input_file = args.input or db_path(cfg, "clinvar", cfg["clinvar"]["variant_summary_file"])
    output_file = args.output or db_path(cfg, "clinvar", cfg["clinvar"]["output_json"])
    assembly = cfg["reference"]["assembly"]

    run(input_file, output_file, assembly)


if __name__ == "__main__":
    main()
