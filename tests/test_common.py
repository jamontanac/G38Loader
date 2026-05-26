"""Tests for g38loader.common — primarily base_dir override logic."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from g38loader.common import BASE_DIR_ENV, load_config


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """A minimal real config.yaml on disk pointing to /from/yaml as base_dir."""
    p = tmp_path / "config.yaml"
    p.write_text(dedent("""\
        base_dir: /from/yaml
        reference:
          assembly: GRCh38
        clinvar:
          subdir: Clinvar
    """))
    return p


def test_load_config_uses_yaml_when_no_overrides(monkeypatch: pytest.MonkeyPatch,
                                                 config_file: Path):
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    cfg = load_config(config_file)
    assert cfg["base_dir"] == "/from/yaml"


def test_explicit_base_dir_kwarg_overrides_yaml(monkeypatch: pytest.MonkeyPatch,
                                                config_file: Path):
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    cfg = load_config(config_file, base_dir="/from/cli")
    assert cfg["base_dir"] == "/from/cli"


def test_env_var_overrides_yaml(monkeypatch: pytest.MonkeyPatch, config_file: Path):
    monkeypatch.setenv(BASE_DIR_ENV, "/from/env")
    cfg = load_config(config_file)
    assert cfg["base_dir"] == "/from/env"


def test_kwarg_wins_over_env_var(monkeypatch: pytest.MonkeyPatch, config_file: Path):
    monkeypatch.setenv(BASE_DIR_ENV, "/from/env")
    cfg = load_config(config_file, base_dir="/from/cli")
    assert cfg["base_dir"] == "/from/cli"


def test_base_dir_path_is_normalized_to_str(monkeypatch: pytest.MonkeyPatch,
                                            config_file: Path):
    """Path objects passed in should be stored as strings (other code does Path(cfg[...]))."""
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    cfg = load_config(config_file, base_dir=Path("/from/cli"))
    assert cfg["base_dir"] == "/from/cli"
    assert isinstance(cfg["base_dir"], str)


def test_yaml_file_not_modified_by_override(monkeypatch: pytest.MonkeyPatch,
                                            config_file: Path):
    """Override is in-memory only; the YAML file on disk is untouched."""
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    load_config(config_file, base_dir="/from/cli")
    body = config_file.read_text()
    assert "/from/yaml" in body
    assert "/from/cli" not in body


def test_empty_env_var_falls_through_to_yaml(monkeypatch: pytest.MonkeyPatch,
                                             config_file: Path):
    """Empty string env var should not override (treated as unset)."""
    monkeypatch.setenv(BASE_DIR_ENV, "")
    cfg = load_config(config_file)
    assert cfg["base_dir"] == "/from/yaml"


def test_load_config_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_expands_tilde_in_kwarg(monkeypatch: pytest.MonkeyPatch,
                                            config_file: Path):
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    cfg = load_config(config_file, base_dir="~/data")
    assert "~" not in cfg["base_dir"]
    assert cfg["base_dir"].endswith("/data")


def test_load_config_expands_tilde_in_env_var(monkeypatch: pytest.MonkeyPatch,
                                              config_file: Path):
    monkeypatch.setenv(BASE_DIR_ENV, "~/from-env")
    cfg = load_config(config_file)
    assert "~" not in cfg["base_dir"]
    assert cfg["base_dir"].endswith("/from-env")


def test_load_config_expands_tilde_in_yaml(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch):
    p = tmp_path / "c.yaml"
    p.write_text("base_dir: ~/yaml-data\n")
    monkeypatch.delenv(BASE_DIR_ENV, raising=False)
    cfg = load_config(p)
    assert "~" not in cfg["base_dir"]
    assert cfg["base_dir"].endswith("/yaml-data")
