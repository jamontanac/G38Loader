#!/usr/bin/env bash
# =============================================================================
# download.sh - fetch all source files for the databases pipeline
#
# Reads URLs and paths from config/config.yaml. Skips files that already
# exist and are non-empty (idempotent).
#
# Requires: wget, yq (https://github.com/mikefarah/yq)
#   On Debian/Ubuntu: apt install wget
#   yq install:       https://github.com/mikefarah/yq#install
#
# Usage:
#   bash download.sh                      # download everything
#   bash download.sh clinvar              # download only ClinVar
#   bash download.sh gnomad chr1 chr22    # gnomAD, just two chromosomes
#   bash download.sh equivalences
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/config/config.yaml"

if ! command -v yq >/dev/null 2>&1; then
    echo "ERROR: yq is required. Install from https://github.com/mikefarah/yq" >&2
    exit 1
fi
if ! command -v wget >/dev/null 2>&1; then
    echo "ERROR: wget is required." >&2
    exit 1
fi

BASE_DIR="$(yq '.base_dir' "$CONFIG")"

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[$(date '+%H:%M:%S')] WARN: $*" >&2; }

# --- helper: download URL into target file unless file already non-empty ----
fetch() {
    local url="$1"
    local target="$2"
    mkdir -p "$(dirname "$target")"
    if [[ -s "$target" ]]; then
        log "SKIP (exists): $target"
        return 0
    fi
    log "GET  $url"
    log "  -> $target"
    wget --quiet --show-progress -O "$target" "$url"
}

# --- helper: gunzip in place if needed -------------------------------------
gunzip_if_needed() {
    local gz="$1"
    local out="$2"
    if [[ -s "$out" ]]; then
        log "SKIP gunzip (exists): $out"
        return 0
    fi
    log "gunzip $gz -> $out"
    gunzip -k -c "$gz" > "$out"
}

# --- ClinVar ---------------------------------------------------------------
download_clinvar() {
    local subdir; subdir="$(yq '.clinvar.subdir' "$CONFIG")"
    local dir="${BASE_DIR}/${subdir}"

    local vs_url; vs_url="$(yq '.clinvar.variant_summary_url' "$CONFIG")"
    local vs_file; vs_file="$(yq '.clinvar.variant_summary_file' "$CONFIG")"
    fetch "$vs_url" "${dir}/${vs_file}.gz"
    gunzip_if_needed "${dir}/${vs_file}.gz" "${dir}/${vs_file}"

    local vcf_url; vcf_url="$(yq '.clinvar.vcf_url' "$CONFIG")"
    local vcf_file; vcf_file="$(yq '.clinvar.vcf_file' "$CONFIG")"
    fetch "$vcf_url" "${dir}/${vcf_file}"
}

# --- OMIM (just symlinks the ClinVar VCF into Omim/) ----------------------
download_omim() {
    local clin_subdir; clin_subdir="$(yq '.clinvar.subdir' "$CONFIG")"
    local clin_vcf;    clin_vcf="$(yq '.clinvar.vcf_file' "$CONFIG")"
    local omim_subdir; omim_subdir="$(yq '.omim.subdir' "$CONFIG")"
    local omim_vcf;    omim_vcf="$(yq '.omim.vcf_file' "$CONFIG")"

    local src="${BASE_DIR}/${clin_subdir}/${clin_vcf}"
    local dst="${BASE_DIR}/${omim_subdir}/${omim_vcf}"

    if [[ ! -s "$src" ]]; then
        warn "ClinVar VCF not yet downloaded; run 'download.sh clinvar' first."
        return 1
    fi
    mkdir -p "$(dirname "$dst")"
    if [[ -e "$dst" ]]; then
        log "SKIP (exists): $dst"
    else
        ln -s "$src" "$dst"
        log "Symlinked $dst -> $src"
    fi
}

# --- Equivalences (NCBI GFF + LRG_RefSeqGene) ------------------------------
download_equivalences() {
    local ncbi_subdir;   ncbi_subdir="$(yq '.equivalences.ncbi_subdir' "$CONFIG")"
    local refseq_subdir; refseq_subdir="$(yq '.equivalences.refseq_subdir' "$CONFIG")"
    local ncbi_dir="${BASE_DIR}/${ncbi_subdir}"
    local refseq_dir="${BASE_DIR}/${refseq_subdir}"

    local gff_url; gff_url="$(yq '.equivalences.ncbi_gff_url' "$CONFIG")"
    local gff_file; gff_file="$(yq '.equivalences.ncbi_gff_file' "$CONFIG")"
    fetch "$gff_url" "${ncbi_dir}/${gff_file}.gz"
    gunzip_if_needed "${ncbi_dir}/${gff_file}.gz" "${ncbi_dir}/${gff_file}"

    local lrg_url; lrg_url="$(yq '.equivalences.refseq_lrg_url' "$CONFIG")"
    local lrg_file; lrg_file="$(yq '.equivalences.refseq_lrg_file' "$CONFIG")"
    fetch "$lrg_url" "${refseq_dir}/${lrg_file}"
}

# --- gnomAD (per-chromosome VCFs) ------------------------------------------
download_gnomad() {
    local subdir; subdir="$(yq '.gnomad.subdir' "$CONFIG")"
    local dir="${BASE_DIR}/${subdir}"
    local url_tmpl; url_tmpl="$(yq '.gnomad.vcf_url_template' "$CONFIG")"
    local file_tmpl; file_tmpl="$(yq '.gnomad.vcf_filename_template' "$CONFIG")"

    local chroms=("$@")
    if [[ ${#chroms[@]} -eq 0 ]]; then
        # all from config
        mapfile -t chroms < <(yq '.gnomad.chromosomes[]' "$CONFIG")
    fi

    for chrom in "${chroms[@]}"; do
        local url="${url_tmpl//\{chrom\}/$chrom}"
        local file="${file_tmpl//\{chrom\}/$chrom}"
        fetch "$url" "${dir}/${file}"
        # Index file (.tbi) — bcftools needs it for region queries
        fetch "${url}.tbi" "${dir}/${file}.tbi" || warn "no .tbi for $chrom"
    done
}

# --- dispatch --------------------------------------------------------------
target="${1:-all}"
shift || true

case "$target" in
    clinvar)       download_clinvar ;;
    omim)          download_omim ;;
    equivalences)  download_equivalences ;;
    gnomad)        download_gnomad "$@" ;;
    all)
        download_clinvar
        download_omim
        download_equivalences
        download_gnomad
        ;;
    *)
        echo "Unknown target: $target" >&2
        echo "Usage: $0 [clinvar|omim|equivalences|gnomad|all] [chroms...]" >&2
        exit 2
        ;;
esac

log "Done."
