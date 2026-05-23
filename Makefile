# =============================================================================
# Databases pipeline
#
# Common targets:
#   make download             # fetch every source file
#   make parse                # run all four parsers
#   make all                  # download + parse
#   make clinvar              # download + parse just ClinVar
#   make gnomad CHROMS=chr1   # download + parse gnomAD for a subset
#   make clean-outputs        # remove generated JSON files (keep raw downloads)
#
# Profile (default dev — ~210 GB. prod adds dbNSFP / SpliceAI / REVEL /
# AlphaMissense / 1000G, ~570+ GB):
#   make download PROFILE=prod
#
# base_dir overrides (default: from config/config.yaml):
#   make download BASE_DIR=/tmp/x       # one-off (exports DATABASES_BASE_DIR)
#   export DATABASES_BASE_DIR=/tmp/x    # session-wide
# =============================================================================

UV ?= uv
DOWNLOAD := $(UV) run download-databases
CONFIG := $(UV) run databases-config

# If the user passes BASE_DIR=..., expose it to every child uv invocation as
# the env var. databases-config / download / parse / verify all read it.
ifdef BASE_DIR
export DATABASES_BASE_DIR := $(BASE_DIR)
endif

# Effective base_dir for shell-side ops (clean-outputs). Prefer the make var
# (set by the export above OR auto-imported from a pre-existing env var);
# fall back to whatever databases-config resolves from the YAML.
EFFECTIVE_BASE_DIR := $(or $(DATABASES_BASE_DIR),$(shell $(CONFIG) base_dir))

# Profile selector: dev (default, ~210 GB) or prod (~570+ GB, includes
# dbNSFP / SpliceAI / REVEL / AlphaMissense / 1000 Genomes).
PROFILE ?= dev

# Override on the command line: make gnomad CHROMS="chr1 chr22"
CHROMS ?=
JOBS ?= 4

.PHONY: all sync test download parse verify clinvar omim equivalences gnomad ensembl dbnsfp spliceai revel alphamissense thousand-genomes clean-outputs help

help:
	@echo "Targets:"
	@echo "  sync             uv sync (install deps + create venv)"
	@echo "  test             Run pytest"
	@echo "  download         Fetch all source files (PROFILE=dev|prod)"
	@echo "  parse            Run all parsers"
	@echo "  verify           Recompute SHA256s and check against READMEs"
	@echo "  all              download + parse"
	@echo "  clinvar          Download + parse ClinVar"
	@echo "  omim             Download + parse OMIM (depends on clinvar download)"
	@echo "  equivalences     Download + parse NCBI/Ensembl equivalences"
	@echo "  gnomad           Download + parse gnomAD (use CHROMS=... for subset)"
	@echo "  ensembl          Download Ensembl regulatory features (no parser)"
	@echo "  dbnsfp           Verify manually-placed dbNSFP files (prod only)"
	@echo "  spliceai         Verify manually-placed SpliceAI files (prod only)"
	@echo "  revel            Download REVEL pathogenicity scores (prod only)"
	@echo "  alphamissense    Download AlphaMissense scores (prod only)"
	@echo "  thousand-genomes Download 1000 Genomes phase3 sites (prod only)"
	@echo "  clean-outputs    Remove generated JSON outputs"

all: download parse

sync:
	$(UV) sync

test:
	$(UV) run --group dev pytest

verify:
	$(UV) run verify-databases

download:
	$(DOWNLOAD) all --profile $(PROFILE) --jobs $(JOBS)

parse:
	$(UV) run parse-clinvar
	$(UV) run parse-omim
	$(UV) run parse-equivalences
	$(UV) run parse-gnomad --jobs $(JOBS) --skip-existing

clinvar:
	$(DOWNLOAD) clinvar
	$(UV) run parse-clinvar

omim:
	$(DOWNLOAD) omim
	$(UV) run parse-omim

equivalences:
	$(DOWNLOAD) equivalences
	$(UV) run parse-equivalences

gnomad:
	$(DOWNLOAD) gnomad $(CHROMS) --jobs $(JOBS)
ifeq ($(strip $(CHROMS)),)
	$(UV) run parse-gnomad --jobs $(JOBS) --skip-existing
else
	$(UV) run parse-gnomad --jobs $(JOBS) --skip-existing --chroms $(CHROMS)
endif

ensembl:
	$(DOWNLOAD) ensembl

dbnsfp:
	$(DOWNLOAD) dbnsfp

spliceai:
	$(DOWNLOAD) spliceai

revel:
	$(DOWNLOAD) revel

alphamissense:
	$(DOWNLOAD) alphamissense

thousand-genomes:
	$(DOWNLOAD) thousand_genomes --jobs $(JOBS)

clean-outputs:
	@echo "Removing generated JSON files in $(EFFECTIVE_BASE_DIR) (raw downloads kept)..."
	@find $(EFFECTIVE_BASE_DIR) -name "variantes_clinvar.json" -delete 2>/dev/null || true
	@find $(EFFECTIVE_BASE_DIR) -name "gene_omim_data.json" -delete 2>/dev/null || true
	@find $(EFFECTIVE_BASE_DIR) -name "equivalencias_transcritos.json" -delete 2>/dev/null || true
	@find $(EFFECTIVE_BASE_DIR) -name "gnomad_AF_chr*.json" -delete 2>/dev/null || true
	@echo "Done."
