"""Tests for databases_processing.preflight."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from databases_processing import preflight as pf

GB = 1024 ** 3


# --------------------------------------------------------------------------
# estimate_total_gb
# --------------------------------------------------------------------------

def test_estimate_total_gb_sums_existing_datasets(fake_config: dict[str, Any]):
    # clinvar=5, omim=0, equivalences=2, gnomad=200, ensembl=0.1 -> 207.1
    total = pf.estimate_total_gb(fake_config,
        ["clinvar", "omim", "equivalences", "gnomad", "ensembl"])
    assert total == pytest.approx(207.1)


def test_estimate_total_gb_subset():
    cfg = {"a": {"estimated_gb": 5}, "b": {"estimated_gb": 10}}
    assert pf.estimate_total_gb(cfg, ["a"]) == 5
    assert pf.estimate_total_gb(cfg, ["a", "b"]) == 15


def test_estimate_total_gb_missing_key_returns_zero():
    cfg = {"a": {}}  # no estimated_gb field
    assert pf.estimate_total_gb(cfg, ["a"]) == 0


def test_estimate_total_gb_unknown_dataset_returns_zero():
    assert pf.estimate_total_gb({}, ["bogus"]) == 0


# --------------------------------------------------------------------------
# free_bytes_for
# --------------------------------------------------------------------------

def test_free_bytes_for_existing_dir(tmp_path: Path):
    # Just check it returns a positive int. Hard to assert exact size.
    assert pf.free_bytes_for(tmp_path) > 0


def test_free_bytes_for_nonexistent_walks_up(tmp_path: Path):
    """If base_dir doesn't exist yet, free space should be reported for the
    nearest existing parent."""
    nonexistent = tmp_path / "does" / "not" / "exist"
    assert pf.free_bytes_for(nonexistent) > 0


# --------------------------------------------------------------------------
# confirm_or_abort — policy
# --------------------------------------------------------------------------

@pytest.fixture
def low_estimate_cfg():
    return {"foo": {"estimated_gb": 1}}


def _stub_free(monkeypatch, gb: float):
    monkeypatch.setattr(pf, "free_bytes_for", lambda _: int(gb * GB))


def test_no_prompt_when_well_under_70_pct(monkeypatch: pytest.MonkeyPatch,
                                           low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=100)  # 1 GB out of 100 GB free = 1%
    # input_fn would raise if called — test it isn't
    pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                        profile="dev", yes=False,
                        input_fn=lambda _: pytest.fail("should not prompt"))


def test_prompts_when_70_to_95_pct(monkeypatch: pytest.MonkeyPatch,
                                    low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1.2)  # 1 GB / 1.2 GB free = 83% -> prompt
    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        return "y"

    pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                        profile="dev", yes=False, input_fn=fake_input)
    assert asked  # prompted


def test_prompt_n_aborts(monkeypatch: pytest.MonkeyPatch,
                         low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1.2)  # forces a prompt
    with pytest.raises(SystemExit):
        pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                            profile="dev", yes=False,
                            input_fn=lambda _: "n")


def test_prompt_empty_aborts(monkeypatch: pytest.MonkeyPatch,
                             low_estimate_cfg, tmp_path: Path):
    """Empty answer (just hitting Enter) defaults to N -> abort."""
    _stub_free(monkeypatch, gb=1.2)
    with pytest.raises(SystemExit):
        pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                            profile="dev", yes=False,
                            input_fn=lambda _: "")


def test_aborts_when_over_95_pct(monkeypatch: pytest.MonkeyPatch,
                                  low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1.0)  # 1 GB / 1 GB free = 100% -> abort
    with pytest.raises(SystemExit):
        pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                            profile="dev", yes=True,  # --yes does NOT bypass abort
                            input_fn=lambda _: pytest.fail("should not prompt"))


def test_yes_skips_prompt(monkeypatch: pytest.MonkeyPatch,
                          low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1.2)  # would normally prompt
    pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                        profile="dev", yes=True,
                        input_fn=lambda _: pytest.fail("should not prompt"))


def test_prod_always_prompts_even_with_lots_of_space(
        monkeypatch: pytest.MonkeyPatch, low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1000)  # 1 GB / 1000 GB free = 0.1%
    asked = []
    pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                        profile="prod", yes=False,
                        input_fn=lambda p: asked.append(p) or "y")
    assert asked  # prod always prompts


def test_prod_with_yes_skips_prompt(monkeypatch: pytest.MonkeyPatch,
                                    low_estimate_cfg, tmp_path: Path):
    _stub_free(monkeypatch, gb=1000)
    pf.confirm_or_abort(low_estimate_cfg, ["foo"], tmp_path,
                        profile="prod", yes=True,
                        input_fn=lambda _: pytest.fail("should not prompt"))


def test_zero_estimate_shortcircuits(monkeypatch: pytest.MonkeyPatch,
                                     tmp_path: Path):
    """If total estimate is 0 GB (e.g., only the OMIM symlink), no prompt."""
    cfg = {"omim": {"estimated_gb": 0}}
    _stub_free(monkeypatch, gb=10)
    pf.confirm_or_abort(cfg, ["omim"], tmp_path,
                        profile="prod", yes=False,
                        input_fn=lambda _: pytest.fail("should not prompt"))


# --------------------------------------------------------------------------
# format_summary — content checks
# --------------------------------------------------------------------------

def test_format_summary_contains_each_dataset(low_estimate_cfg, tmp_path: Path):
    out = pf.format_summary(low_estimate_cfg, ["foo"], tmp_path,
                            estimated_gb=1, free_gb=100, profile="dev")
    assert "foo" in out
    assert "1.0 GB" in out
    assert "dev" in out
    assert str(tmp_path) in out


def test_format_summary_handles_empty_list(tmp_path: Path):
    out = pf.format_summary({}, [], tmp_path,
                            estimated_gb=0, free_gb=100, profile="dev")
    assert "(none)" in out
