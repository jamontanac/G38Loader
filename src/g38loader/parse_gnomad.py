"""Extract allele frequencies from gnomAD VCFs into per-chromosome JSON.

Replaces the original extraction_freq.py + txt_freq_to_json.py pair.
For each chromosome:
    1. Run `bcftools query` to pull CHROM/POS/REF/ALT/AF
    2. Stream the output into a JSON file (no intermediate .txt to clean up)
    3. Optional: run multiple chromosomes in parallel

Requires `bcftools` on PATH.

Usage:
    # All chromosomes from config, 4 in parallel
    python parse_gnomad.py --jobs 4

    # Specific chromosomes
    python parse_gnomad.py --chroms chr1 chr22

    # Override the input directory
    python parse_gnomad.py --vcf-dir /custom/path --chroms chr15
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from g38loader.common import load_config, setup_logging

log = logging.getLogger("parse_gnomad")


def check_bcftools() -> None:
    if shutil.which("bcftools") is None:
        raise RuntimeError("bcftools not found on PATH. Install it before running.")


def process_one(vcf_file: Path, output_json: Path) -> tuple[str, int]:
    """Run bcftools on one VCF and write its JSON. Returns (chrom_label, n_records)."""
    if not vcf_file.is_file():
        raise FileNotFoundError(f"VCF not found: {vcf_file}")

    log.info("[%s] querying with bcftools...", vcf_file.name)
    cmd = [
        "bcftools", "query",
        "-f", "%CHROM\t%POS\t%REF\t%ALT\t%AF\n",
        str(vcf_file),
    ]

    output_json.parent.mkdir(parents=True, exist_ok=True)

    # Stream bcftools stdout line-by-line straight into JSON to avoid
    # holding the whole chromosome in memory if it's very large.
    records: list[dict] = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 5:
                continue
            chrom, pos, ref, alt, af = parts
            try:
                af_val = float(af)
            except ValueError:
                af_val = 0.0
            records.append({
                "CHROM": chrom,
                "POS": int(pos),
                "REF": ref,
                "ALT": alt,
                "AF": af_val,
            })
        ret = proc.wait()
        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd)

    with output_json.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=4)

    log.info("[%s] wrote %d records to %s",
             vcf_file.name, len(records), output_json.name)
    return vcf_file.name, len(records)


def iter_jobs(cfg: dict, vcf_dir: Path, output_dir: Path,
              chroms: Iterable[str]) -> list[tuple[Path, Path]]:
    """Build the list of (input_vcf, output_json) pairs to process."""
    g = cfg["gnomad"]
    version = g["version"]
    jobs: list[tuple[Path, Path]] = []
    for chrom in chroms:
        vcf_name = g["vcf_filename_template"].format(chrom=chrom, version=version)
        out_name = g["output_json_template"].format(chrom=chrom)
        jobs.append((vcf_dir / vcf_name, output_dir / out_name))
    return jobs


def run(cfg: dict, vcf_dir: Path, output_dir: Path,
        chroms: list[str], jobs: int, skip_existing: bool) -> None:
    check_bcftools()
    pairs = iter_jobs(cfg, vcf_dir, output_dir, chroms)

    if skip_existing:
        before = len(pairs)
        pairs = [(v, o) for v, o in pairs if not o.is_file() or o.stat().st_size == 0]
        log.info("Skip-existing: %d -> %d jobs", before, len(pairs))

    log.info("Running %d job(s) with %d worker(s)", len(pairs), jobs)
    if jobs <= 1:
        for vcf, out in pairs:
            try:
                process_one(vcf, out)
            except Exception as e:
                log.error("Failed on %s: %s", vcf.name, e)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = {ex.submit(process_one, v, o): v.name for v, o in pairs}
            for fut in concurrent.futures.as_completed(futures):
                name = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    log.error("Failed on %s: %s", name, e)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--vcf-dir", type=Path, default=None,
                        help="Directory holding gnomAD VCFs (defaults to config)")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Where to write per-chrom JSON (defaults to vcf-dir)")
    parser.add_argument("--chroms", nargs="+", default=None,
                        help="Subset of chromosomes (e.g. chr1 chr22). Default: all from config.")
    parser.add_argument("--jobs", type=int, default=1,
                        help="Parallel chromosomes to process (default 1)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip chromosomes that already have a non-empty JSON output")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load_config(args.config, base_dir=args.base_dir)

    base = Path(cfg["base_dir"])
    vcf_dir = args.vcf_dir or (base / cfg["gnomad"]["subdir"])
    output_dir = args.output_dir or vcf_dir
    chroms = args.chroms or cfg["gnomad"]["chromosomes"]

    run(cfg, vcf_dir, output_dir, chroms, args.jobs, args.skip_existing)


if __name__ == "__main__":
    main()
