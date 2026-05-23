"""Extract Gene -> OMIM mappings from a ClinVar VCF.

ClinVar VCF INFO fields contain GENEINFO=<symbol>:<id> and one or more
OMIM:<id> entries inside the CLNDISDB / MC fields. We collect every
unique (gene, OMIM) pair across the file.

Usage:
    python parse_omim.py \\
        --input /datadrive/Databases/Omim/clinvar.vcf.gz \\
        --output /datadrive/Databases/Omim/gene_omim_data.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
from pathlib import Path
from typing import Iterable

from databases_processing.common import load_config, db_path, setup_logging

log = logging.getLogger("parse_omim")

GENEINFO_RE = re.compile(r"GENEINFO=([^;:\t]+):\d+")
# Capture every OMIM:<digits> in the line; ClinVar can list several per variant
OMIM_RE = re.compile(r"OMIM:(\d+)")


def iter_vcf_lines(vcf_path: Path) -> Iterable[str]:
    """Yield non-header lines from a gzipped or plain VCF."""
    opener = gzip.open if vcf_path.suffix == ".gz" else open
    with opener(vcf_path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                yield line


def run(vcf_path: Path, output_file: Path, max_lines: int | None = None) -> None:
    log.info("Reading ClinVar VCF: %s", vcf_path)

    pairs: dict[tuple[str, str], dict] = {}
    variant_count = 0

    for line in iter_vcf_lines(vcf_path):
        variant_count += 1
        cols = line.split("\t")
        if len(cols) <= 7:
            continue
        info = cols[7]

        gene_match = GENEINFO_RE.search(info)
        if not gene_match:
            continue
        gene = gene_match.group(1)

        # Collect every OMIM id mentioned for this variant
        for omim_code in OMIM_RE.findall(info):
            key = (gene, omim_code)
            if key not in pairs:
                pairs[key] = {
                    "Gen": gene,
                    "Omim": omim_code,
                    "enlace_Omim": f"https://www.omim.org/entry/{omim_code}",
                }

        if variant_count % 100_000 == 0:
            log.info("  processed %d variants, %d unique pairs so far",
                     variant_count, len(pairs))

        if max_lines and variant_count >= max_lines:
            log.info("Reached max_lines=%d, stopping", max_lines)
            break

    log.info("Total: %d variants scanned, %d unique (gene, OMIM) pairs",
             variant_count, len(pairs))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(list(pairs.values()), f, indent=2, ensure_ascii=False)
    log.info("Wrote %s", output_file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--input", type=Path, default=None,
                        help="Override path to clinvar.vcf.gz")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-lines", type=int, default=None,
                        help="Stop after N variants (debug)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load_config(args.config, base_dir=args.base_dir)

    input_file = args.input or db_path(cfg, "omim", cfg["omim"]["vcf_file"])
    output_file = args.output or db_path(cfg, "omim", cfg["omim"]["output_json"])

    run(input_file, output_file, args.max_lines)


if __name__ == "__main__":
    main()
