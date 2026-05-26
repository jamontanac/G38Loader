"""Tests for g38loader.config_cli."""
from __future__ import annotations

import pytest

from g38loader.config_cli import resolve


def test_resolve_simple_key():
    assert resolve({"base_dir": "/foo"}, "base_dir") == "/foo"


def test_resolve_dotted_key():
    cfg = {"clinvar": {"version": "1.0"}}
    assert resolve(cfg, "clinvar.version") == "1.0"


def test_resolve_three_levels_deep():
    cfg = {"a": {"b": {"c": 42}}}
    assert resolve(cfg, "a.b.c") == 42


def test_resolve_missing_top_key():
    with pytest.raises(KeyError, match="missing_key"):
        resolve({}, "missing_key")


def test_resolve_missing_nested_key():
    with pytest.raises(KeyError, match="clinvar.missing"):
        resolve({"clinvar": {}}, "clinvar.missing")


def test_resolve_descending_into_non_dict():
    # 'gnomad.chromosomes.chr1' should fail because chromosomes is a list
    with pytest.raises(KeyError):
        resolve({"gnomad": {"chromosomes": ["chr1"]}}, "gnomad.chromosomes.chr1")
