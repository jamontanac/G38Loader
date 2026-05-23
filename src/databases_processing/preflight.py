"""Pre-flight checks before a download run.

Prints a summary of which datasets will be downloaded plus disk-space
status. Decides whether to proceed silently, prompt the user, or hard-abort
based on the policy:

    estimated <= 70% of free   : print summary, no prompt
    70% < estimated <= 95%     : print + interactive y/N prompt
    estimated > 95% of free    : hard abort
    profile == "prod"          : ALWAYS prompt (overrides the above)
    --yes                      : skip the prompt (disk-space abort still applies)
"""
from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("preflight")

# Thresholds expressed as a fraction of free space at base_dir.
WARN_FRACTION = 0.70
ABORT_FRACTION = 0.95
GB = 1024 ** 3


def estimate_total_gb(cfg: dict, dataset_names: list[str]) -> float:
    """Sum the `estimated_gb` field across the given datasets."""
    total = 0.0
    for name in dataset_names:
        section = cfg.get(name, {})
        total += float(section.get("estimated_gb", 0))
    return total


def free_bytes_for(path: Path) -> int:
    """`shutil.disk_usage` requires an existing path; walk up if needed."""
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def format_summary(cfg: dict, dataset_names: list[str], base_dir: Path,
                   estimated_gb: float, free_gb: float, profile: str) -> str:
    """Build a human-readable summary string."""
    lines = [
        "",
        "=" * 64,
        f"Pre-flight check (profile: {profile})",
        "=" * 64,
        "Datasets to download:",
    ]
    if not dataset_names:
        lines.append("  (none)")
    else:
        for name in dataset_names:
            section = cfg.get(name, {})
            est = section.get("estimated_gb", 0)
            lines.append(f"  {name:<20s} ~{est:>6.1f} GB")
    lines += [
        "-" * 64,
        f"Total estimate:        ~{estimated_gb:>6.1f} GB",
        f"Free at {str(base_dir):<24s} {free_gb:>6.1f} GB",
        "=" * 64,
    ]
    return "\n".join(lines)


def confirm_or_abort(cfg: dict, dataset_names: list[str], base_dir: Path,
                     profile: str, yes: bool = False,
                     input_fn=input) -> None:
    """Print summary, then either return (proceed), prompt, or abort.

    Always raises SystemExit on abort. Returns None when caller should proceed.
    """
    estimated_gb = estimate_total_gb(cfg, dataset_names)
    free = free_bytes_for(base_dir)
    free_gb = free / GB

    summary = format_summary(cfg, dataset_names, base_dir,
                             estimated_gb, free_gb, profile)
    print(summary, file=sys.stderr)

    if estimated_gb == 0:
        # Nothing to download (e.g., only the omim symlink).
        return

    fraction = estimated_gb / free_gb if free_gb > 0 else float("inf")
    if fraction > ABORT_FRACTION:
        print(
            f"ABORT: estimated {estimated_gb:.1f} GB exceeds "
            f"{ABORT_FRACTION:.0%} of free space ({free_gb:.1f} GB).\n"
            f"Free disk space or override BASE_DIR / DATABASES_BASE_DIR "
            f"to a larger volume.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    must_prompt = (profile == "prod") or (fraction > WARN_FRACTION)
    if not must_prompt or yes:
        return

    try:
        answer = input_fn("Proceed? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print("Aborted by user.", file=sys.stderr)
        raise SystemExit(1)
