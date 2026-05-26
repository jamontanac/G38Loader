"""Write per-dataset provenance README.md files.

Each README documents what landed in a dataset directory: dataset name,
version, last-updated timestamp, assembly, and a table of files with
source URLs / derivation notes, sizes, and SHA256 checksums.

Checksums are computed on every run so the README always reflects the
current bytes on disk and can be diffed across environments.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
from pathlib import Path

log = logging.getLogger("provenance")

CHUNK_SIZE = 1024 * 1024  # 1 MB


FileSpec = tuple[Path, str]  # (path, source_url_or_note)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(n_bytes: int) -> str:
    n = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def write_readme(
    *,
    dataset_name: str,
    output_dir: Path,
    version: str,
    description: str,
    files: list[FileSpec],
    assembly: str | None = None,
    extra_metadata: dict[str, str] | None = None,
) -> Path:
    """Write a Markdown README.md to output_dir documenting the dataset.

    Files are listed in the order given. Missing files are skipped with a
    warning. SHA256 is computed for every existing file (full read).
    Write is atomic via a `.part` rename.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# {dataset_name}",
        "",
        f"- Last updated: {now_utc()}",
        f"- Version:      {version}",
    ]
    if assembly:
        lines.append(f"- Assembly:     {assembly}")
    if extra_metadata:
        for k, v in extra_metadata.items():
            lines.append(f"- {k}: {v}")

    lines += [
        "",
        "## Files",
        "",
        "| File | Source | Size | SHA256 |",
        "|------|--------|------|--------|",
    ]

    for file_path, source in files:
        if not file_path.exists():
            log.warning("Skipping missing file in README: %s", file_path)
            continue
        size = human_size(file_path.stat().st_size)
        log.info("Computing SHA256 for %s (%s)...", file_path.name, size)
        digest = sha256_file(file_path)
        lines.append(f"| `{file_path.name}` | {source} | {size} | `{digest}` |")

    lines += ["", "## Notes", "", description.strip(), ""]

    target = output_dir / "README.md"
    part = Path(f"{target}.part")
    part.write_text("\n".join(lines), encoding="utf-8")
    part.replace(target)
    log.info("Wrote provenance README: %s", target)
    return target
