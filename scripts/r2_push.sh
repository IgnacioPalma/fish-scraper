#!/usr/bin/env bash
# Sube a Cloudflare R2, desde el árbol local data/, los componentes indicados.
#
# Uso:
#   scripts/r2_push.sh                 # los productos finales (output)
#   scripts/r2_push.sh copernicus      # solo las grillas Copernicus
#   scripts/r2_push.sh raw             # todo el corpus crudo
#   scripts/r2_push.sh raw output      # crudo + productos
#
# Componentes: ifop | registry | vms | copernicus | raw | output
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
. scripts/r2_common.sh

[ "$#" -eq 0 ] && set -- output

for comp in "$@"; do
  r2_paths "$comp" | while read -r prefix dir; do
    [ -z "$prefix" ] && continue
    if [ ! -d "$dir" ]; then
      echo "  (omito ${dir}: no existe localmente)"
      continue
    fi
    echo "local → R2: ${dir}  →  s3://${R2_BUCKET}/${prefix}"
    r2_sync "$dir" "s3://${R2_BUCKET}/${prefix}"
  done
done
echo "Listo (push)."
