"""Verify dataset files against the provenance READMEs.

Walks each dataset's directory, parses the SHA256 column from README.md, and
recomputes the digest of each listed file. Reports OK / MISMATCH / MISSING
and exits non-zero if anything is off — useful as a CI check or after copying
data between machines.

Usage:
    verify-databases                   # all datasets
    verify-databases clinvar gnomad    # subset
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from g38loader.common import db_path, load_config, setup_logging
from g38loader.provenance import sha256_file

log = logging.getLogger("verify")

# Matches a data row in the README's file table:
#   | `<filename>` | <source> | <size> | `<64-hex sha256>` |
ROW_RE = re.compile(
    r"^\|\s*`([^`]+)`\s*\|[^|]*\|[^|]*\|\s*`([0-9a-fA-F]{64})`\s*\|\s*$"
)


def parse_readme_files(readme: Path) -> list[tuple[str, str]]:
    """Return [(filename, expected_sha256), ...] from a README.md table."""
    out: list[tuple[str, str]] = []
    for line in readme.read_text(encoding="utf-8").splitlines():
        m = ROW_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2).lower()))
    return out


def verify_dir(d: Path) -> tuple[int, int, int]:
    """Verify files listed in d/README.md. Returns (n_ok, n_mismatch, n_missing)."""
    readme = d / "README.md"
    if not readme.is_file():
        log.warning("No README.md in %s — skipping", d)
        return (0, 0, 0)

    rows = parse_readme_files(readme)
    if not rows:
        log.warning("No file rows parsed from %s", readme)
        return (0, 0, 0)

    n_ok = n_mm = n_missing = 0
    for fname, expected in rows:
        p = d / fname
        if not p.exists():
            log.error("MISSING:  %s", p)
            n_missing += 1
            continue
        log.info("Verifying %s...", fname)
        actual = sha256_file(p)
        if actual == expected:
            log.info("  OK     %s", fname)
            n_ok += 1
        else:
            log.error("MISMATCH: %s (expected %s, got %s)", p, expected, actual)
            n_mm += 1
    return (n_ok, n_mm, n_missing)


TARGET_DIRS = {
    "clinvar":          lambda cfg: [db_path(cfg, "clinvar")],
    "omim":             lambda cfg: [db_path(cfg, "omim")],
    "equivalences":     lambda cfg: [db_path(cfg, "equivalences.ncbi"),
                                     db_path(cfg, "equivalences.refseq")],
    "gnomad":           lambda cfg: [Path(cfg["base_dir"]) / cfg["gnomad"]["subdir"]],
    "ensembl":          lambda cfg: [db_path(cfg, "ensembl")],
    "dbnsfp":           lambda cfg: [db_path(cfg, "dbnsfp")],
    "spliceai":         lambda cfg: [db_path(cfg, "spliceai")],
    "revel":            lambda cfg: [db_path(cfg, "revel")],
    "alphamissense":    lambda cfg: [db_path(cfg, "alphamissense")],
    "thousand_genomes": lambda cfg: [db_path(cfg, "thousand_genomes")],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("targets", nargs="*",
                        choices=[*TARGET_DIRS.keys(), "all"], default=None,
                        help="Datasets to verify (default: all)")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load_config(args.config, base_dir=args.base_dir)

    targets = args.targets or list(TARGET_DIRS.keys())
    if "all" in targets:
        targets = list(TARGET_DIRS.keys())

    total_ok = total_mm = total_missing = 0
    for t in targets:
        for d in TARGET_DIRS[t](cfg):
            ok, mm, missing = verify_dir(d)
            total_ok += ok
            total_mm += mm
            total_missing += missing

    log.info("Summary: %d OK, %d mismatched, %d missing",
             total_ok, total_mm, total_missing)
    if total_mm or total_missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
