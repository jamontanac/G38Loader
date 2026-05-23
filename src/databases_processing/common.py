"""Shared utilities for the databases pipeline.

Loads the YAML config once and exposes helpers for building paths
in a uniform way across all parser scripts.

`base_dir` overrides
--------------------
The `base_dir` field in `config/config.yaml` can be overridden without
editing the file. Precedence (highest wins):

    1. The `base_dir=` kwarg to `load_config()` — set by `--base-dir` CLI flag
    2. The `DATABASES_BASE_DIR` environment variable
    3. The value in the YAML file

Overrides are applied in-memory to the returned dict only; the file is
never modified.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

# src/databases_processing/common.py -> repo root is parents[2]
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

# Env var that overrides cfg["base_dir"]. CLI flag (--base-dir) still wins.
BASE_DIR_ENV = "DATABASES_BASE_DIR"


def load_config(path: str | Path | None = None,
                *, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Load the pipeline YAML config and apply optional `base_dir` overrides.

    Override precedence (highest wins): `base_dir` kwarg, then the
    `DATABASES_BASE_DIR` env var, then the value in the file.
    """
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)

    override = base_dir if base_dir is not None else os.environ.get(BASE_DIR_ENV)
    if override:
        cfg["base_dir"] = str(override)
    # Expand `~` in whichever base_dir we ended up with. Lets users pass
    # `--base-dir ~/data` or `BASE_DIR=~/data` even when the shell didn't
    # do tilde expansion (zsh w/o MAGIC_EQUAL_SUBST, env vars, etc).
    cfg["base_dir"] = str(Path(cfg["base_dir"]).expanduser())
    return cfg


def db_path(config: dict[str, Any], section: str, *parts: str) -> Path:
    """Resolve <base_dir>/<section.subdir>/<parts...>.

    Special-case 'equivalences' which has two subdirs (ncbi + refseq).
    Pass the subdir key explicitly via `section` like 'equivalences.ncbi'.
    """
    base = Path(config["base_dir"])
    if "." in section:
        top, sub = section.split(".", 1)
        subdir = config[top][f"{sub}_subdir"]
    else:
        subdir = config[section]["subdir"]
    return base.joinpath(subdir, *parts)


def setup_logging(level: str = "INFO") -> None:
    """Standard logging format for all scripts."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def ensure_dir(path: Path) -> Path:
    """Create directory if missing; return the path for chaining."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_exists_nonempty(path: Path) -> bool:
    """True if a file exists and has non-zero size."""
    return path.is_file() and path.stat().st_size > 0
