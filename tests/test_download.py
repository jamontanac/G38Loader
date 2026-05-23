"""Tests for databases_processing.download."""
from __future__ import annotations

import gzip
import subprocess
from pathlib import Path
from typing import Any

import pytest

from databases_processing import download as dl


# --------------------------------------------------------------------------
# fetch()
# --------------------------------------------------------------------------

def test_fetch_skips_existing_nonempty_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "already.bin"
    target.write_bytes(b"already here")

    called = []
    monkeypatch.setattr(dl.subprocess, "run",
                        lambda *a, **kw: called.append((a, kw)))

    assert dl.fetch("http://example.test/x", target) is True
    assert called == []
    assert target.read_bytes() == b"already here"


def test_fetch_atomic_rename_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"
    part = Path(f"{target}.part")

    def fake_run(cmd, **kwargs):
        # cmd ends with [..., "-O", part_path, url]
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"downloaded")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    assert dl.fetch("http://example.test/x", target) is True
    assert target.read_bytes() == b"downloaded"
    assert not part.exists()


def test_fetch_failure_cleans_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"
    part = Path(f"{target}.part")

    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"partial")
        raise subprocess.CalledProcessError(8, cmd)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        dl.fetch("http://example.test/x", target)
    assert not part.exists()
    assert not target.exists()


def test_fetch_allow_failure_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    assert dl.fetch("http://example.test/x", target, allow_failure=True) is False


def test_fetch_falls_back_when_primary_fails(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch):
    """When the primary URL fails, fetch tries the fallback and uses its bytes."""
    target = tmp_path / "out.bin"
    attempts: list[str] = []

    def fake_run(cmd, **kwargs):
        url = cmd[-1]
        attempts.append(url)
        if "primary" in url:
            raise subprocess.CalledProcessError(4, cmd)
        # fallback succeeds
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"from-fallback")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    ok = dl.fetch("http://primary.test/x", target,
                  fallback_urls=("http://fallback.test/x",))
    assert ok is True
    assert target.read_bytes() == b"from-fallback"
    assert attempts == ["http://primary.test/x", "http://fallback.test/x"]


def test_fetch_does_not_use_fallback_when_primary_succeeds(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"
    attempts: list[str] = []

    def fake_run(cmd, **kwargs):
        url = cmd[-1]
        attempts.append(url)
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"from-primary")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    dl.fetch("http://primary.test/x", target,
             fallback_urls=("http://fallback.test/x",))
    assert attempts == ["http://primary.test/x"]
    assert target.read_bytes() == b"from-primary"


def test_fetch_all_mirrors_failing_raises(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(4, cmd)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        dl.fetch("http://primary.test/x", target,
                 fallback_urls=("http://fallback.test/x",))


def test_fetch_all_mirrors_failing_with_allow_failure_returns_false(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "out.bin"

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(4, cmd)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    ok = dl.fetch("http://primary.test/x", target,
                  fallback_urls=("http://fallback.test/x",),
                  allow_failure=True)
    assert ok is False


def test_fetch_creates_parent_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "deep" / "nested" / "out.bin"

    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"ok")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    dl.fetch("http://example.test/x", target)
    assert target.exists()


# --------------------------------------------------------------------------
# gunzip_if_needed()
# --------------------------------------------------------------------------

def test_gunzip_if_needed_skips_existing(tmp_path: Path):
    gz = tmp_path / "src.gz"
    gz.write_bytes(b"\x1f\x8b\x08")  # invalid gz body — would crash if we tried
    out = tmp_path / "src"
    out.write_bytes(b"already decompressed")

    dl.gunzip_if_needed(gz, out)  # must not raise
    assert out.read_bytes() == b"already decompressed"


def test_gunzip_if_needed_decompresses(tmp_path: Path):
    payload = b"hello, world\n" * 100
    gz = tmp_path / "src.gz"
    with gzip.open(gz, "wb") as f:
        f.write(payload)
    out = tmp_path / "src"

    dl.gunzip_if_needed(gz, out)
    assert out.read_bytes() == payload


# --------------------------------------------------------------------------
# run_fetches()
# --------------------------------------------------------------------------

def test_run_fetches_serial_calls_each(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls = []
    monkeypatch.setattr(dl, "fetch",
                        lambda url, target, **kw: calls.append((url, target)) or True)
    jobs = [
        dl.FetchJob("http://example.test/a", tmp_path / "a"),
        dl.FetchJob("http://example.test/b", tmp_path / "b"),
    ]
    dl.run_fetches(jobs, n_workers=1)
    assert len(calls) == 2


def test_run_fetches_passes_fallback_urls_through(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    """run_fetches should forward FetchJob.fallback_urls to fetch()."""
    seen_fallbacks = []
    monkeypatch.setattr(dl, "fetch",
                        lambda url, target, *, fallback_urls=(), **kw:
                            seen_fallbacks.append(fallback_urls) or True)
    jobs = [
        dl.FetchJob("http://primary.test/a", tmp_path / "a",
                    fallback_urls=("http://fb1.test/a", "http://fb2.test/a")),
    ]
    dl.run_fetches(jobs, n_workers=1)
    assert seen_fallbacks == [("http://fb1.test/a", "http://fb2.test/a")]


def test_run_fetches_empty_is_noop(monkeypatch: pytest.MonkeyPatch):
    called = []
    monkeypatch.setattr(dl, "fetch", lambda *a, **kw: called.append(True))
    dl.run_fetches([], n_workers=4)
    assert called == []


# --------------------------------------------------------------------------
# CLI dispatch
# --------------------------------------------------------------------------

def test_main_rejects_chroms_for_non_gnomad(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["download-databases", "clinvar", "chr1"])
    with pytest.raises(SystemExit) as ei:
        dl.main()
    assert ei.value.code == 2


# --------------------------------------------------------------------------
# Profile filtering
# --------------------------------------------------------------------------

def test_datasets_for_profile_dev(fake_config: dict[str, Any]):
    names = dl.datasets_for_profile(fake_config, "dev")
    # Test fixture marks all 5 existing datasets as both dev and prod.
    assert names == ["clinvar", "omim", "equivalences", "gnomad", "ensembl"]


def test_datasets_for_profile_prod(fake_config: dict[str, Any]):
    names = dl.datasets_for_profile(fake_config, "prod")
    # All 10 datasets — 5 dev/prod and 5 prod-only — in canonical dispatch order
    assert names == [
        "clinvar", "omim", "equivalences", "gnomad", "ensembl",
        "dbnsfp", "spliceai", "revel", "alphamissense", "thousand_genomes",
    ]


def test_datasets_for_profile_excludes_when_profile_missing(fake_config: dict[str, Any]):
    # Strip 'prod' from gnomad's profiles -> it should be excluded
    fake_config["gnomad"]["profiles"] = ["dev"]
    assert "gnomad" not in dl.datasets_for_profile(fake_config, "prod")
    assert "gnomad" in dl.datasets_for_profile(fake_config, "dev")


def test_datasets_for_profile_unknown_profile_returns_empty(fake_config: dict[str, Any]):
    assert dl.datasets_for_profile(fake_config, "bogus") == []


def test_main_warns_and_returns_when_no_datasets_match(
        monkeypatch: pytest.MonkeyPatch, fake_config: dict[str, Any],
        caplog: pytest.LogCaptureFixture):
    # Strip every profile so no dataset matches
    for name in dl.ALL_DATASETS:
        if name in fake_config:
            fake_config[name].pop("profiles", None)

    monkeypatch.setattr("sys.argv", ["download-databases", "--profile", "dev"])
    monkeypatch.setattr(dl, "check_wget", lambda: None)
    monkeypatch.setattr(dl, "load_config",
                        lambda path=None, *, base_dir=None: fake_config)
    caplog.set_level("WARNING")
    dl.main()
    assert "No datasets match profile=dev" in caplog.text


def test_main_explicit_target_works_regardless_of_profile(
        monkeypatch: pytest.MonkeyPatch, fake_config: dict[str, Any]):
    """Even if a target is excluded from the active profile, calling it
    explicitly should still dispatch."""
    fake_config["clinvar"]["profiles"] = ["prod"]  # not in dev

    calls = []
    monkeypatch.setattr("sys.argv",
                        ["download-databases", "clinvar", "--profile", "dev"])
    monkeypatch.setattr(dl, "check_wget", lambda: None)
    monkeypatch.setattr(dl, "load_config",
                        lambda path=None, *, base_dir=None: fake_config)
    monkeypatch.setattr(dl, "confirm_or_abort", lambda *a, **kw: None)
    monkeypatch.setattr(dl, "download_clinvar",
                        lambda cfg, jobs: calls.append("clinvar"))

    dl.main()
    assert calls == ["clinvar"]


def test_main_default_target_is_all(monkeypatch: pytest.MonkeyPatch, fake_config: dict[str, Any]):
    """With no positional args, dispatch every target in order."""
    monkeypatch.setattr("sys.argv", ["download-databases"])
    monkeypatch.setattr(dl, "check_wget", lambda: None)
    monkeypatch.setattr(dl, "load_config",
                        lambda path=None, *, base_dir=None: fake_config)
    monkeypatch.setattr(dl, "confirm_or_abort", lambda *a, **kw: None)

    calls = []
    monkeypatch.setattr(dl, "download_clinvar",
                        lambda cfg, jobs: calls.append("clinvar"))
    monkeypatch.setattr(dl, "download_omim",
                        lambda cfg: calls.append("omim"))
    monkeypatch.setattr(dl, "download_equivalences",
                        lambda cfg, jobs: calls.append("equivalences"))
    monkeypatch.setattr(dl, "download_gnomad",
                        lambda cfg, jobs, chroms: calls.append("gnomad"))
    monkeypatch.setattr(dl, "download_ensembl",
                        lambda cfg, jobs: calls.append("ensembl"))

    dl.main()
    assert calls == ["clinvar", "omim", "equivalences", "gnomad", "ensembl"]


# --------------------------------------------------------------------------
# Target-level integration (fetches mocked, README real)
# --------------------------------------------------------------------------

def test_download_clinvar_writes_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        fake_config: dict[str, Any]):
    """Mock wget so the 'downloads' just write fixed bytes; verify README + files."""
    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"fake gz body")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    # Replace gunzip with a stub that just writes plain text (so we can assert content).
    def fake_gunzip(gz: Path, out: Path):
        out.write_bytes(b"decompressed body")

    monkeypatch.setattr(dl, "gunzip_if_needed", fake_gunzip)

    dl.download_clinvar(fake_config, jobs=1)

    clinvar_dir = Path(fake_config["base_dir"]) / "Clinvar"
    assert (clinvar_dir / "variant_summary.txt.gz").exists()
    assert (clinvar_dir / "variant_summary.txt").exists()
    assert (clinvar_dir / "clinvar.vcf.gz").exists()

    readme = (clinvar_dir / "README.md").read_text()
    assert "# ClinVar" in readme
    assert "weekly_snapshot" in readme
    assert "GRCh38" in readme
    assert "variant_summary.txt.gz" in readme


def test_download_omim_warns_when_clinvar_missing(monkeypatch: pytest.MonkeyPatch,
                                                  fake_config: dict[str, Any],
                                                  caplog: pytest.LogCaptureFixture):
    # No clinvar VCF was created -> download_omim should warn and bail.
    caplog.set_level("WARNING")
    dl.download_omim(fake_config)
    assert "ClinVar VCF not yet downloaded" in caplog.text


def test_download_ensembl_writes_readme(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch,
                                        fake_config: dict[str, Any]):
    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"fake gff3 body")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    monkeypatch.setattr(dl, "gunzip_if_needed",
                        lambda gz, out: out.write_bytes(b"decompressed"))

    dl.download_ensembl(fake_config, jobs=1)

    out_dir = Path(fake_config["base_dir"]) / "Ensembl"
    assert (out_dir / "regulatory.gff3.gz").exists()
    assert (out_dir / "regulatory.gff3").exists()

    readme = (out_dir / "README.md").read_text()
    assert "# Ensembl regulatory features" in readme
    assert "release-112" in readme
    assert "regulatory.gff3" in readme


def test_download_gnomad_uses_version_template(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch,
                                               fake_config: dict[str, Any]):
    """The {version} placeholder in URL + filename templates must be substituted."""
    seen_urls: list[str] = []
    seen_targets: list[Path] = []

    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        url = cmd[-1]
        target = Path(cmd[out_idx + 1])
        seen_urls.append(url)
        seen_targets.append(target)
        target.write_bytes(b"fake")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    dl.download_gnomad(fake_config, jobs=1, chroms=["chr1"])

    # Expect URL to have v4.1 and filename to have v4.1
    assert any("v4.1" in u for u in seen_urls)
    assert any("gnomad.v4.1.chr1" in str(t) for t in seen_targets)
    # Primary mirror is tried first
    assert seen_urls[0].startswith("http://primary.test/")

    out_dir = Path(fake_config["base_dir"]) / "Gnomad" / "DataVCF"
    readme = (out_dir / "README.md").read_text()
    assert "# gnomAD exomes" in readme
    assert "Version:      4.1" in readme
    assert "Dataset: exomes" in readme


# --------------------------------------------------------------------------
# Phase-3 datasets: dbNSFP / SpliceAI / REVEL / AlphaMissense / 1000G
# --------------------------------------------------------------------------

def test_dbnsfp_warns_when_file_missing(monkeypatch: pytest.MonkeyPatch,
                                        fake_config: dict[str, Any],
                                        caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING")
    dl.download_dbnsfp(fake_config)
    assert "dbNSFP requires a manual download" in caplog.text
    # No README written when file is missing
    out_dir = Path(fake_config["base_dir"]) / "dbNSFP"
    assert not (out_dir / "README.md").exists()


def test_dbnsfp_writes_readme_when_file_present(monkeypatch: pytest.MonkeyPatch,
                                                 fake_config: dict[str, Any]):
    out_dir = Path(fake_config["base_dir"]) / "dbNSFP"
    out_dir.mkdir(parents=True)
    (out_dir / "dbNSFP5.0a.gz").write_bytes(b"fake dbnsfp body")

    dl.download_dbnsfp(fake_config)

    readme = (out_dir / "README.md").read_text()
    assert "# dbNSFP" in readme
    assert "5.0a" in readme
    assert "manual download" in readme


def test_spliceai_warns_when_files_missing(monkeypatch: pytest.MonkeyPatch,
                                           fake_config: dict[str, Any],
                                           caplog: pytest.LogCaptureFixture):
    caplog.set_level("WARNING")
    dl.download_spliceai(fake_config)
    assert "SpliceAI requires a manual download" in caplog.text


def test_spliceai_writes_readme_when_both_files_present(
        monkeypatch: pytest.MonkeyPatch, fake_config: dict[str, Any]):
    out_dir = Path(fake_config["base_dir"]) / "SpliceAI"
    out_dir.mkdir(parents=True)
    (out_dir / "spliceai_scores.raw.snv.hg38.vcf.gz").write_bytes(b"snv")
    (out_dir / "spliceai_scores.raw.indel.hg38.vcf.gz").write_bytes(b"indel")

    dl.download_spliceai(fake_config)
    readme = (out_dir / "README.md").read_text()
    assert "# SpliceAI" in readme
    assert "snv.hg38" in readme
    assert "indel.hg38" in readme


def test_spliceai_warns_when_one_of_two_files_missing(
        monkeypatch: pytest.MonkeyPatch, fake_config: dict[str, Any],
        caplog: pytest.LogCaptureFixture):
    out_dir = Path(fake_config["base_dir"]) / "SpliceAI"
    out_dir.mkdir(parents=True)
    (out_dir / "spliceai_scores.raw.snv.hg38.vcf.gz").write_bytes(b"snv")
    # indel file deliberately missing
    caplog.set_level("WARNING")
    dl.download_spliceai(fake_config)
    assert "Missing now" in caplog.text
    assert "indel" in caplog.text


def test_download_revel_writes_readme(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch,
                                      fake_config: dict[str, Any]):
    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"fake revel zip body")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    dl.download_revel(fake_config, jobs=1)
    out_dir = Path(fake_config["base_dir"]) / "REVEL"
    assert (out_dir / "revel-v1.3_all_chromosomes.zip").exists()
    readme = (out_dir / "README.md").read_text()
    assert "# REVEL" in readme


def test_download_alphamissense_writes_readme(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch,
                                              fake_config: dict[str, Any]):
    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"fake AM body")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    dl.download_alphamissense(fake_config, jobs=1)
    out_dir = Path(fake_config["base_dir"]) / "AlphaMissense"
    assert (out_dir / "AlphaMissense_hg38.tsv.gz").exists()
    readme = (out_dir / "README.md").read_text()
    assert "# AlphaMissense" in readme


def test_download_thousand_genomes_per_chromosome(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  fake_config: dict[str, Any]):
    seen_urls: list[str] = []

    def fake_run(cmd, **kwargs):
        out_idx = cmd.index("-O")
        url = cmd[-1]
        seen_urls.append(url)
        Path(cmd[out_idx + 1]).write_bytes(b"fake 1000g body")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    dl.download_thousand_genomes(fake_config, jobs=1)

    # Fixture has chromosomes ["1", "X"]; we expect both URLs hit
    assert any("chr1.vcf.gz" in u for u in seen_urls)
    assert any("chrX.vcf.gz" in u for u in seen_urls)
    out_dir = Path(fake_config["base_dir"]) / "ThousandGenomes"
    readme = (out_dir / "README.md").read_text()
    assert "# 1000 Genomes Project" in readme


# --------------------------------------------------------------------------
# Existing gnomAD test follows
# --------------------------------------------------------------------------

def test_download_gnomad_falls_back_to_secondary_mirror(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        fake_config: dict[str, Any]):
    """If the primary mirror NXDOMAINs, gnomAD should fall back to the secondary."""
    seen_urls: list[str] = []

    def fake_run(cmd, **kwargs):
        url = cmd[-1]
        seen_urls.append(url)
        if "primary.test" in url:
            raise subprocess.CalledProcessError(4, cmd)
        out_idx = cmd.index("-O")
        Path(cmd[out_idx + 1]).write_bytes(b"fake")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dl.subprocess, "run", fake_run)

    dl.download_gnomad(fake_config, jobs=1, chroms=["chr1"])

    # Primary tried first, then fallback
    chr1_attempts = [u for u in seen_urls if "chr1" in u and ".tbi" not in u]
    assert chr1_attempts[0].startswith("http://primary.test/")
    assert chr1_attempts[1].startswith("http://fallback.test/")
