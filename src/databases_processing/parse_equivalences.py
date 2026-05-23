"""Build ENST -> [NM, NP] transcript-equivalence map.

Sources:
    1. NCBI RefSeq GFF (GRCh38_latest_genomic.gff)
       Lines have Dbxref=...,Ensembl:ENST...,GenBank:NM_...
       This gives us ENST -> NM.
    2. RefSeq LRG_RefSeqGene.txt
       Tab-delimited table with NM (col 6) and NP (col 8).
       This gives us NM -> NP.

Final output: { "ENST00000xxxxxx": ["NM_xxxxxx", "NP_xxxxxx"], ... }

Usage:
    python parse_equivalences.py \\
        --ncbi-gff /datadrive/Databases/NCBI_gff/GRCh38_latest_genomic.gff \\
        --refseq-lrg /datadrive/Databases/RefGene/LRG_RefSeqGene.txt \\
        --output /datadrive/Databases/NCBI_gff/equivalencias_transcritos.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from databases_processing.common import load_config, db_path, setup_logging

log = logging.getLogger("parse_equivalences")

ENSEMBL_RE = re.compile(r"Ensembl:([^,;]+)")
GENBANK_RE = re.compile(r"GenBank:([^,;]+)")


def parse_ncbi_gff(file_path: Path) -> dict[str, str]:
    """Return {ENST_id_unversioned: NM_id} from the NCBI GFF."""
    mapping: dict[str, str] = {}
    log.info("Parsing NCBI GFF: %s", file_path)
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9:
                continue
            attributes = fields[-1]

            ens = ENSEMBL_RE.search(attributes)
            if not ens:
                continue
            ensembl_id = ens.group(1)
            if not ensembl_id.startswith("ENST"):
                continue

            gb = GENBANK_RE.search(attributes)
            genbank_id = gb.group(1) if gb else "NA"

            # Strip version suffix on the ENST id (.1, .2, etc)
            ensembl_id_clean = ensembl_id.split(".", 1)[0]
            mapping[ensembl_id_clean] = genbank_id
    log.info("  found %d ENST -> NM entries", len(mapping))
    return mapping


def parse_lrg_refseq(file_path: Path) -> dict[str, str]:
    """Return {NM_id: NP_id} from the LRG_RefSeqGene.txt table."""
    mapping: dict[str, str] = {}
    log.info("Parsing LRG_RefSeqGene: %s", file_path)
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 8:
                continue
            nm = fields[5]
            np = fields[7] or "NA"
            mapping[nm] = np
    log.info("  found %d NM -> NP entries", len(mapping))
    return mapping


def merge(enst_to_nm: dict[str, str], nm_to_np: dict[str, str]) -> dict[str, list[str]]:
    """Combine both maps into ENST -> [NM, NP]."""
    out: dict[str, list[str]] = {}
    for enst, nm in enst_to_nm.items():
        np = nm_to_np.get(nm, "NA")
        out[enst] = [nm, np]
    return out


def run(ncbi_gff: Path, refseq_lrg: Path, output_file: Path) -> None:
    enst_to_nm = parse_ncbi_gff(ncbi_gff)
    nm_to_np = parse_lrg_refseq(refseq_lrg)
    merged = merge(enst_to_nm, nm_to_np)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=4)
    log.info("Wrote %d entries to %s", len(merged), output_file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--ncbi-gff", type=Path, default=None)
    parser.add_argument("--refseq-lrg", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load_config(args.config, base_dir=args.base_dir)

    ncbi_gff = args.ncbi_gff or db_path(cfg, "equivalences.ncbi",
                                        cfg["equivalences"]["ncbi_gff_file"])
    refseq_lrg = args.refseq_lrg or db_path(cfg, "equivalences.refseq",
                                            cfg["equivalences"]["refseq_lrg_file"])
    output = args.output or db_path(cfg, "equivalences.ncbi",
                                    cfg["equivalences"]["output_json"])

    run(ncbi_gff, refseq_lrg, output)


if __name__ == "__main__":
    main()
