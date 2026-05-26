"""Download all source files for the databases pipeline.

Python orchestrator + wget transfer engine. Reads URLs and paths from
config/config.yaml; skips files that already exist non-empty (idempotent).
Downloads land in `<target>.part` first and are atomically renamed on success
so an interrupted run never leaves a half-file that looks complete.

Requires `wget` on PATH.

Usage:
    uv run download-databases                       # all
    uv run download-databases clinvar               # single target
    uv run download-databases gnomad chr1 chr22     # gnomAD subset
    uv run download-databases gnomad --jobs 4       # parallel fetches
    uv run download-databases all --jobs 4          # parallel within each target
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

from g38loader.common import (
    db_path,
    file_exists_nonempty,
    load_config,
    setup_logging,
)
from g38loader.preflight import confirm_or_abort
from g38loader.provenance import FileSpec, write_readme

log = logging.getLogger("download")


class FetchJob(NamedTuple):
    """One download. `fallback_urls` are tried in order if `url` fails."""
    url: str
    target: Path
    fallback_urls: tuple[str, ...] = ()


def check_wget() -> None:
    if shutil.which("wget") is None:
        raise RuntimeError("wget not found on PATH. Install it before running.")


def fetch(url: str, target: Path, *,
          fallback_urls: tuple[str, ...] = (),
          allow_failure: bool = False,
          show_progress: bool = True) -> bool:
    """Download URL to target via wget. Tries `url` first; on failure walks
    `fallback_urls` in order. Idempotent + atomic via .part rename.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if file_exists_nonempty(target):
        log.info("SKIP (exists): %s", target)
        return True

    part = Path(f"{target}.part")
    candidates = (url, *fallback_urls)
    last_error: subprocess.CalledProcessError | None = None

    for i, candidate in enumerate(candidates):
        log.info("GET  %s -> %s", candidate, target)

        # --no-verbose: errors + a single completion line, no full transfer log.
        # --show-progress (with --no-verbose) keeps the progress bar in serial mode.
        cmd = ["wget", "--no-verbose"]
        if show_progress:
            cmd.append("--show-progress")
        cmd += ["-O", str(part), candidate]

        try:
            subprocess.run(cmd, check=True)
            part.rename(target)
            log.info("DONE %s", target)
            return True
        except subprocess.CalledProcessError as e:
            part.unlink(missing_ok=True)
            last_error = e
            remaining = len(candidates) - i - 1
            if remaining:
                log.warning("Mirror failed (rc=%d): %s — trying next (%d left)",
                            e.returncode, candidate, remaining)

    # All candidates failed.
    if allow_failure:
        log.warning("All %d mirror(s) failed for %s", len(candidates), target)
        return False
    assert last_error is not None
    raise last_error


def gunzip_if_needed(gz: Path, out: Path) -> None:
    if file_exists_nonempty(out):
        log.info("SKIP gunzip (exists): %s", out)
        return
    log.info("gunzip %s -> %s", gz, out)
    with gzip.open(gz, "rb") as src, out.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def run_fetches(jobs: list[FetchJob], n_workers: int, *,
                allow_failure: bool = False) -> None:
    """Run a batch of fetch jobs, serially or in parallel."""
    if not jobs:
        return
    if n_workers <= 1:
        for job in jobs:
            fetch(job.url, job.target,
                  fallback_urls=job.fallback_urls,
                  allow_failure=allow_failure, show_progress=True)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {
            ex.submit(fetch, job.url, job.target,
                      fallback_urls=job.fallback_urls,
                      allow_failure=allow_failure, show_progress=False): job.target
            for job in jobs
        }
        for fut in concurrent.futures.as_completed(futures):
            fut.result()


# --------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------

def download_clinvar(cfg: dict, jobs: int) -> None:
    c = cfg["clinvar"]
    out_dir = db_path(cfg, "clinvar")
    vs_gz = out_dir / (c["variant_summary_file"] + ".gz")
    vs_txt = out_dir / c["variant_summary_file"]
    vcf = out_dir / c["vcf_file"]

    run_fetches([
        FetchJob(c["variant_summary_url"], vs_gz),
        FetchJob(c["vcf_url"], vcf),
    ], jobs)
    gunzip_if_needed(vs_gz, vs_txt)

    write_readme(
        dataset_name="ClinVar",
        output_dir=out_dir,
        version=c["version"],
        description=c["description"],
        assembly=cfg["reference"]["assembly"],
        files=[
            (vs_gz, c["variant_summary_url"]),
            (vs_txt, f"decompressed from `{vs_gz.name}`"),
            (vcf, c["vcf_url"]),
        ],
    )


def download_omim(cfg: dict) -> None:
    o = cfg["omim"]
    src = db_path(cfg, "clinvar", cfg["clinvar"]["vcf_file"])
    out_dir = db_path(cfg, "omim")
    dst = out_dir / o["vcf_file"]
    if not file_exists_nonempty(src):
        log.warning("ClinVar VCF not yet downloaded; "
                    "run 'download-databases clinvar' first.")
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        log.info("SKIP (exists): %s", dst)
    else:
        os.symlink(src, dst)
        log.info("Symlinked %s -> %s", dst, src)

    write_readme(
        dataset_name="OMIM",
        output_dir=out_dir,
        version=o["version"],
        description=o["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(dst, f"symlink -> `{src}`")],
    )


def download_equivalences(cfg: dict, jobs: int) -> None:
    e = cfg["equivalences"]
    ncbi_dir = db_path(cfg, "equivalences.ncbi")
    refseq_dir = db_path(cfg, "equivalences.refseq")
    gff_gz = ncbi_dir / (e["ncbi_gff_file"] + ".gz")
    gff = ncbi_dir / e["ncbi_gff_file"]
    lrg = refseq_dir / e["refseq_lrg_file"]

    run_fetches([
        FetchJob(e["ncbi_gff_url"], gff_gz),
        FetchJob(e["refseq_lrg_url"], lrg),
    ], jobs)
    gunzip_if_needed(gff_gz, gff)

    write_readme(
        dataset_name="Equivalences (NCBI GFF)",
        output_dir=ncbi_dir,
        version=e["version"],
        description=e["description"],
        assembly=cfg["reference"]["assembly"],
        files=[
            (gff_gz, e["ncbi_gff_url"]),
            (gff, f"decompressed from `{gff_gz.name}`"),
        ],
    )
    write_readme(
        dataset_name="Equivalences (LRG_RefSeqGene)",
        output_dir=refseq_dir,
        version=e["version"],
        description=e["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(lrg, e["refseq_lrg_url"])],
    )


def download_gnomad(cfg: dict, jobs: int, chroms: list[str] | None) -> None:
    g = cfg["gnomad"]
    version = g["version"]
    out_dir = Path(cfg["base_dir"]) / g["subdir"]
    chroms = chroms or g["chromosomes"]

    templates = g["vcf_url_templates"]
    if not templates:
        raise ValueError("gnomad.vcf_url_templates must contain at least one URL")

    fmt_kwargs = {"version": version}

    vcf_jobs: list[FetchJob] = []
    tbi_jobs: list[FetchJob] = []
    chrom_specs: list[tuple[Path, str, Path, str]] = []  # vcf_path, primary_url, tbi_path, primary_tbi_url
    for chrom in chroms:
        urls = [t.format(chrom=chrom, **fmt_kwargs) for t in templates]
        primary, *fallbacks = urls
        fname = g["vcf_filename_template"].format(chrom=chrom, **fmt_kwargs)
        vcf_path = out_dir / fname

        tbi_urls = [f"{u}.tbi" for u in urls]
        tbi_primary, *tbi_fallbacks = tbi_urls
        tbi_path = Path(f"{vcf_path}.tbi")

        vcf_jobs.append(FetchJob(primary, vcf_path, tuple(fallbacks)))
        tbi_jobs.append(FetchJob(tbi_primary, tbi_path, tuple(tbi_fallbacks)))
        chrom_specs.append((vcf_path, primary, tbi_path, tbi_primary))

    run_fetches(vcf_jobs, jobs)
    # .tbi is best-effort; matches `|| warn` in the bash version
    run_fetches(tbi_jobs, jobs, allow_failure=True)

    # README lists every configured chromosome's VCF + .tbi that exists on disk.
    files: list[FileSpec] = []
    for vcf_path, vcf_url, tbi_path, tbi_url in chrom_specs:
        files.append((vcf_path, vcf_url))
        files.append((tbi_path, tbi_url))
    files = [(p, s) for p, s in files if p.exists()]

    write_readme(
        dataset_name=f"gnomAD {g['dataset']}",
        output_dir=out_dir,
        version=version,
        description=g["description"],
        assembly=cfg["reference"]["assembly"],
        extra_metadata={"Dataset": g["dataset"]},
        files=files,
    )


def download_ensembl(cfg: dict, jobs: int) -> None:
    e = cfg["ensembl"]
    out_dir = db_path(cfg, "ensembl")
    gff_gz = out_dir / (e["regulatory_features_file"] + ".gz")
    gff = out_dir / e["regulatory_features_file"]

    run_fetches([FetchJob(e["regulatory_features_url"], gff_gz)], jobs)
    gunzip_if_needed(gff_gz, gff)

    write_readme(
        dataset_name="Ensembl regulatory features",
        output_dir=out_dir,
        version=e["version"],
        description=e["description"],
        assembly=cfg["reference"]["assembly"],
        files=[
            (gff_gz, e["regulatory_features_url"]),
            (gff, f"decompressed from `{gff_gz.name}`"),
        ],
    )


def _check_manual_dataset(dataset_name: str, out_dir: Path,
                          expected_files: list[str], download_url: str) -> bool:
    """Verify all expected files exist on disk; if not, log instructions and
    return False so the caller can skip the README write.

    Used for datasets whose distributors require a license click-through or
    auth login (dbNSFP, SpliceAI). The pipeline can't fetch them automatically,
    but it can tell the user exactly where to drop them.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    missing = [f for f in expected_files if not file_exists_nonempty(out_dir / f)]
    if not missing:
        return True

    log.warning("=" * 72)
    log.warning("%s requires a manual download (license / auth required).", dataset_name)
    log.warning("  1. Visit: %s", download_url)
    log.warning("  2. Accept the license / sign in.")
    log.warning("  3. Place the file(s) at:")
    for f in expected_files:
        log.warning("       %s", out_dir / f)
    log.warning("  4. Re-run `download-databases %s` to record provenance.",
                dataset_name.lower().replace(" ", "_"))
    log.warning("Missing now: %s", ", ".join(missing))
    log.warning("=" * 72)
    return False


def download_dbnsfp(cfg: dict) -> None:
    d = cfg["dbnsfp"]
    out_dir = db_path(cfg, "dbnsfp")
    expected = d["expected_files"]
    if not _check_manual_dataset("dbNSFP", out_dir, expected, d["download_url"]):
        return

    write_readme(
        dataset_name="dbNSFP",
        output_dir=out_dir,
        version=d["version"],
        description=d["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(out_dir / f, f"manual download from {d['download_url']}")
               for f in expected],
    )


def download_spliceai(cfg: dict) -> None:
    s = cfg["spliceai"]
    out_dir = db_path(cfg, "spliceai")
    expected = s["expected_files"]
    if not _check_manual_dataset("SpliceAI", out_dir, expected, s["download_url"]):
        return

    write_readme(
        dataset_name="SpliceAI",
        output_dir=out_dir,
        version=s["version"],
        description=s["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(out_dir / f, f"manual download from {s['download_url']}")
               for f in expected],
    )


def download_revel(cfg: dict, jobs: int) -> None:
    r = cfg["revel"]
    out_dir = db_path(cfg, "revel")
    target = out_dir / r["download_filename"]
    run_fetches([FetchJob(r["download_url"], target)], jobs)

    write_readme(
        dataset_name="REVEL",
        output_dir=out_dir,
        version=r["version"],
        description=r["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(target, r["download_url"])],
    )


def download_alphamissense(cfg: dict, jobs: int) -> None:
    a = cfg["alphamissense"]
    out_dir = db_path(cfg, "alphamissense")
    target = out_dir / a["download_filename"]
    run_fetches([FetchJob(a["download_url"], target)], jobs)

    write_readme(
        dataset_name="AlphaMissense",
        output_dir=out_dir,
        version=a["version"],
        description=a["description"],
        assembly=cfg["reference"]["assembly"],
        files=[(target, a["download_url"])],
    )


def download_thousand_genomes(cfg: dict, jobs: int) -> None:
    tg = cfg["thousand_genomes"]
    out_dir = db_path(cfg, "thousand_genomes")
    chroms = tg["chromosomes"]

    fetch_jobs: list[FetchJob] = []
    file_specs: list[FileSpec] = []
    for chrom in chroms:
        url = tg["vcf_url_template"].format(chrom=chrom)
        fname = tg["vcf_filename_template"].format(chrom=chrom)
        target = out_dir / fname
        fetch_jobs.append(FetchJob(url, target))
        file_specs.append((target, url))

    run_fetches(fetch_jobs, jobs)

    # Only list files that actually exist (some chroms may have failed)
    files_present = [(p, u) for p, u in file_specs if p.exists()]
    write_readme(
        dataset_name="1000 Genomes Project",
        output_dir=out_dir,
        version=tg["version"],
        description=tg["description"],
        assembly=cfg["reference"]["assembly"],
        files=files_present,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

# Datasets in dispatch order. The "all" target walks this list, filtered by
# --profile membership (each dataset's `profiles:` list in config.yaml).
ALL_DATASETS: tuple[str, ...] = (
    "clinvar",
    "omim",
    "equivalences",
    "gnomad",
    "ensembl",
    "dbnsfp",
    "spliceai",
    "revel",
    "alphamissense",
    "thousand_genomes",
)
PROFILES: tuple[str, ...] = ("dev", "prod")
TARGETS: tuple[str, ...] = (*ALL_DATASETS, "all")


def datasets_for_profile(cfg: dict, profile: str) -> list[str]:
    """Return the ordered list of dataset names that belong to `profile`.

    Walks ALL_DATASETS, including only datasets that exist in cfg AND list
    `profile` in their `profiles:` field.
    """
    out: list[str] = []
    for name in ALL_DATASETS:
        section = cfg.get(name)
        if not isinstance(section, dict):
            continue
        if profile in section.get("profiles", []):
            out.append(name)
    return out


def _run_target(name: str, cfg: dict, jobs: int,
                gnomad_chroms: list[str] | None = None) -> None:
    """Dispatch a single dataset name to its downloader."""
    if name == "clinvar":
        download_clinvar(cfg, jobs)
    elif name == "omim":
        download_omim(cfg)
    elif name == "equivalences":
        download_equivalences(cfg, jobs)
    elif name == "gnomad":
        download_gnomad(cfg, jobs, gnomad_chroms)
    elif name == "ensembl":
        download_ensembl(cfg, jobs)
    elif name == "dbnsfp":
        download_dbnsfp(cfg)
    elif name == "spliceai":
        download_spliceai(cfg)
    elif name == "revel":
        download_revel(cfg, jobs)
    elif name == "alphamissense":
        download_alphamissense(cfg, jobs)
    elif name == "thousand_genomes":
        download_thousand_genomes(cfg, jobs)
    else:
        raise ValueError(f"Unknown dataset: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("target", nargs="?", default="all", choices=TARGETS,
                        help="What to download (default: all)")
    parser.add_argument("chroms", nargs="*",
                        help="Optional chromosome subset (only valid with `gnomad`)")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    parser.add_argument("--profile", choices=PROFILES, default="dev",
                        help="Which dataset profile to include in `all` "
                             "(default: dev). Has no effect on explicit targets.")
    parser.add_argument("--jobs", "-j", type=int, default=1,
                        help="Parallel fetches per target (default 1)")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip pre-flight confirmation prompt")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    setup_logging(args.log_level)
    if args.chroms and args.target != "gnomad":
        parser.error(
            f"chrom args only valid with target=gnomad, got target={args.target}"
        )

    check_wget()
    cfg = load_config(args.config, base_dir=args.base_dir)
    j = max(1, args.jobs)

    if args.target == "all":
        targets = datasets_for_profile(cfg, args.profile)
        if not targets:
            log.warning("No datasets match profile=%s; nothing to do.", args.profile)
            return
        confirm_or_abort(cfg, targets, Path(cfg["base_dir"]),
                         profile=args.profile, yes=args.yes)
        for name in targets:
            _run_target(name, cfg, j)
    else:
        # Single explicit target — also pre-flight (estimated_gb may matter)
        confirm_or_abort(cfg, [args.target], Path(cfg["base_dir"]),
                         profile=args.profile, yes=args.yes)
        _run_target(args.target, cfg, j, gnomad_chroms=args.chroms or None)

    log.info("Done.")


if __name__ == "__main__":
    main()
