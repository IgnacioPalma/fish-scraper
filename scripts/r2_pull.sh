#!/usr/bin/env bash
# Descarga desde Cloudflare R2 al árbol local data/ los componentes indicados.
#
# Uso:
#   scripts/r2_pull.sh                 # corpus crudo completo (raw)
#   scripts/r2_pull.sh copernicus      # solo las grillas Copernicus (todas)
#   scripts/r2_pull.sh copernicus-nc   # solo las 4 grillas .nc que usa el pipeline
#   scripts/r2_pull.sh ifop registry   # varios componentes
#   scripts/r2_pull.sh output          # los productos finales
#
# Componentes: ifop | registry | vms | capture | copernicus | copernicus-nc | raw | output
# Todo el corpus cuelga de raw/; solo copernicus/output van prefijados por región
# (REGION, ver r2_common.sh): p.ej. raw/chile/copernicus, mientras el resto del
# corpus es nacional (raw/ifop, …). El árbol local data/ NO cambia con la región.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. scripts/r2_common.sh

[ "$#" -eq 0 ] && set -- raw

for comp in "$@"; do
  r2_paths "$comp" | while read -r prefix dir; do
    [ -z "$prefix" ] && continue
    mkdir -p "$dir"
    echo "R2 → local: s3://${R2_BUCKET}/${prefix}  →  ${dir}"
    if [ "$comp" = "copernicus-nc" ]; then
      # Solo las grillas .nc que abre sample_haul_environment; el resto de la
      # carpeta (csv, sla, wind) no se usa y llenaba el disco del runner.
      r2_sync "s3://${R2_BUCKET}/${prefix}" "$dir" \
        --exclude '*' \
        --include 'sst_atacama_*.nc' --include 'chl_atacama_*.nc' \
        --include 'phy_atacama_*.nc' --include 'bgc_atacama_*.nc'
    else
      r2_sync "s3://${R2_BUCKET}/${prefix}" "$dir"
    fi
  done
done
echo "Listo (pull)."
