#!/usr/bin/env bash
# Descarga desde Cloudflare R2 al árbol local data/ los componentes indicados.
#
# Uso:
#   scripts/r2_pull.sh                 # corpus crudo completo (raw)
#   scripts/r2_pull.sh copernicus      # solo las grillas Copernicus
#   scripts/r2_pull.sh ifop registry   # varios componentes
#   scripts/r2_pull.sh output          # los productos finales
#
# Componentes: ifop | registry | vms | capture | copernicus | raw | output
# Las claves R2 van prefijadas por región (REGION, ver r2_common.sh): p.ej.
# raw/chile/copernicus. El árbol local data/ NO cambia con la región.
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
    r2_sync "s3://${R2_BUCKET}/${prefix}" "$dir"
  done
done
echo "Listo (pull)."
