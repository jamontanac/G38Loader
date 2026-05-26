# G38Loader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

GRCh38-anchored pipeline for downloading, verifying, and parsing ClinVar, gnomAD,
OMIM, and other major genomic reference databases into structured JSON.

- **Reference assembly:** GRCh38
- **gnomAD dataset:** exomes v4.1.1
- **Ensembl release:** 112 (regulatory features GFF3)
- **Output format:** JSON
- **Managed by:** [uv](https://github.com/astral-sh/uv)

## Layout

```
g38loader/
├── pyproject.toml                  # project + deps + console scripts
├── uv.lock
├── Makefile                        # orchestration
├── config/config.yaml              # paths, URLs, versions, descriptions
├── src/g38loader/
│   ├── common.py                   # config loader + path helpers
│   ├── config_cli.py               # databases-config (replaces yq)
│   ├── download.py                 # download-databases
│   ├── verify.py                   # verify-databases (SHA256 check)
│   ├── provenance.py               # README writer
│   ├── parse_clinvar.py            # variant_summary.txt -> JSON
│   ├── parse_omim.py               # ClinVar VCF -> gene/OMIM JSON
│   ├── parse_equivalences.py       # NCBI GFF + LRG -> ENST/NM/NP JSON
│   └── parse_gnomad.py             # gnomAD VCFs -> per-chrom AF JSON
└── tests/                          # pytest suite
```

## Requirements

- Python 3.10+ (managed by uv)
- `uv` on PATH
- `wget` on PATH (for downloads)
- `bcftools` on PATH (for `parse-gnomad`)

## Quick start

```bash
# Install deps + create venv
make sync

# Run the test suite
make test

# Everything end to end
make all

# Or step by step
make download
make parse

# Just one database
make clinvar
make equivalences

# gnomAD for a subset of chromosomes, 8 in parallel
make gnomad CHROMS="chr1 chr22 chrX" JOBS=8

# Verify what's on disk against the per-dataset README.md SHA256s
make verify
```

Each console script also has its own `--help`:

```bash
uv run download-databases --help
uv run parse-clinvar --help
uv run verify-databases --help
uv run databases-config --help
```

## Profiles (dev vs prod)

The pipeline ships with two **profiles** controlling which datasets get
included by `download-databases all`:

- **`dev`** (default, ~210 GB): ClinVar, OMIM, Equivalences, gnomAD, Ensembl
  regulatory features. Suitable for laptop / development work.
- **`prod`** (~570+ GB): everything in dev *plus* dbNSFP, SpliceAI, REVEL,
  AlphaMissense, and 1000 Genomes Project phase 3 sites VCFs. Requires
  significant disk and (for dbNSFP / SpliceAI) manual license acceptance.

```bash
# Default (dev) — small set, no prompts unless space is tight
make download

# Full set — pre-flight banner + interactive y/N prompt unless --yes
make download PROFILE=prod
uv run download-databases --profile prod
uv run download-databases --profile prod --yes   # CI / scripted
```

A pre-flight summary always prints before any download starts: estimated
total GB, free space at `base_dir`, and a y/N prompt when the estimate is
between 70% and 95% of free space (or when `--profile prod` is selected).
The run hard-aborts if the estimate exceeds 95% of free space.

Each dataset's `profiles:` membership and `estimated_gb:` are declared in
`config/config.yaml`. Explicit targets (e.g. `download-databases revel`)
always work regardless of profile.

### Datasets that require manual download

Two prod datasets need a one-time manual download because of license
click-through (dbNSFP) or BaseSpace login (SpliceAI). When you run
`download-databases dbnsfp` or `spliceai` the first time, the pipeline
will print exact instructions and the expected file paths. Place the
files there and re-run to record a provenance README.

## Configuration overrides

`config/config.yaml` is the source of truth and should not need to be edited
for routine work. The `base_dir` can be overridden in three ways, with the
following precedence (highest wins):

1. **CLI flag `--base-dir PATH`** — per-command override:

   ```bash
   uv run download-databases clinvar --base-dir /tmp/test
   uv run verify-databases --base-dir /tmp/test
   uv run databases-config base_dir --base-dir /tmp/test   # prints /tmp/test
   ```

2. **Environment variable `DATABASES_BASE_DIR`** — session-wide override:

   ```bash
   export DATABASES_BASE_DIR=/tmp/test
   uv run download-databases clinvar
   uv run parse-clinvar
   ```

3. **The YAML file** — fallback when neither of the above is set.

The override is applied in-memory only; `config/config.yaml` is never
modified. The destination directory does not need to exist beforehand —
`download-databases` will create it.

The `make` orchestrator forwards `BASE_DIR=...` as the env var, so all
sub-invocations within a single `make` run see it:

```bash
make download BASE_DIR=/tmp/test         # one-off
make all      BASE_DIR=/tmp/test
```

## Provenance README files

After every successful download, a `README.md` is written into each dataset
directory recording: dataset name, version, last-updated UTC timestamp,
GRCh38 assembly, and a table of files with their source URL, size, and
**SHA256**. `verify-databases` uses these to confirm the bytes on disk match
what was originally downloaded — useful when copying data between machines.

## Output files

After a full run:

| Database         | Profile | Output                                                                                              |
|------------------|---------|-----------------------------------------------------------------------------------------------------|
| ClinVar          | dev+prod | `<base_dir>/Clinvar/variantes_clinvar.json`                                                        |
| OMIM             | dev+prod | `<base_dir>/Omim/gene_omim_data.json`                                                              |
| Equivalences     | dev+prod | `<base_dir>/NCBI_gff/equivalencias_transcritos.json`                                               |
| gnomAD           | dev+prod | `<base_dir>/Gnomad/DataVCF/gnomad_AF_chr{N}.json`                                                  |
| Ensembl          | dev+prod | `<base_dir>/Ensembl/Homo_sapiens.GRCh38.regulatory_features.v112.gff3` (download only — no parser) |
| dbNSFP           | prod    | `<base_dir>/dbNSFP/dbNSFP5.0a.gz` (manual download — no parser)                                    |
| SpliceAI         | prod    | `<base_dir>/SpliceAI/spliceai_scores.raw.{snv,indel}.hg38.vcf.gz` (manual download)                |
| REVEL            | prod    | `<base_dir>/REVEL/revel-v1.3_all_chromosomes.zip` (download only)                                  |
| AlphaMissense    | prod    | `<base_dir>/AlphaMissense/AlphaMissense_hg38.tsv.gz` (download only)                               |
| 1000 Genomes     | prod    | `<base_dir>/ThousandGenomes/ALL.chr{N}.GRCh38.phased.vcf.gz` (download only)                       |

## Notes / gotchas

- **ClinVar `variant_summary.txt`** contains both GRCh37 and GRCh38 rows.
  The parser filters to GRCh38 to avoid duplicates.
- **OMIM extractor** captures *every* OMIM ID per variant, not just the first.
  ClinVar variants frequently link to multiple conditions.
- **Equivalences** only keep entries with both an Ensembl ENST and a GenBank
  cross-reference in the GFF. NM-only or ENST-only transcripts are skipped.
- **gnomAD** uses `bcftools query` and streams output to JSON. JSON files
  for large chromosomes (chr1, chr2) can reach several GB.
- **Idempotent:** `download-databases` skips files that already exist
  non-empty; downloads are atomic via `<file>.part` rename.
- **gnomAD `.tbi` failures are tolerated** — the index file is best-effort
  per chromosome; missing `.tbi`s log a warning but don't fail the run.

## Updating

When a new gnomAD or ClinVar release lands, edit `config/config.yaml`
(URLs and `version:` strings) and re-run `make all`. The provenance README
SHA256s will change to reflect the new bytes.
