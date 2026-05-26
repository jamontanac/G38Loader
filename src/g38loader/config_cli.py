"""Print a value from the pipeline config using a dotted key path.

Replaces `yq '.<key>' config/config.yaml` with a Python implementation so we
don't need yq as a system dependency.

Examples:
    databases-config base_dir          # /datadrive/Databases
    databases-config gnomad.version    # 4.1
    databases-config clinvar.subdir    # Clinvar
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from g38loader.common import load_config


def resolve(cfg: dict[str, Any], key: str) -> Any:
    """Walk a dotted key path through nested dicts. Lists are not indexed."""
    val: Any = cfg
    for part in key.split("."):
        if not isinstance(val, dict) or part not in val:
            raise KeyError(f"Config key not found: {key}")
        val = val[part]
    return val


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("key", help="Dotted key path (e.g. 'base_dir', 'gnomad.version')")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-dir", type=Path, default=None,
                        help="Override base_dir (also: $DATABASES_BASE_DIR env var)")
    args = parser.parse_args()

    cfg = load_config(args.config, base_dir=args.base_dir)
    try:
        print(resolve(cfg, args.key))
    except KeyError as e:
        print(str(e).strip("'"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
