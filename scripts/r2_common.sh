#!/usr/bin/env bash
# Helper común para sincronizar con Cloudflare R2 (compatible con la API de S3).
# Se hace `source` desde r2_pull.sh / r2_push.sh. NO ejecutar directamente.
#
# Credenciales: se leen del entorno (en CI vienen de los secrets de GitHub); si
# existe un `.env` en la raíz, también se carga para uso local. Variables:
#   R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
#   R2_ENDPOINT  (o bien R2_ACCOUNT_ID, del que se deriva el endpoint)
set -euo pipefail

# Carga .env si está presente (uso local); en CI las vars ya están en el entorno.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

: "${R2_BUCKET:?falta R2_BUCKET}"
: "${R2_ACCESS_KEY_ID:?falta R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?falta R2_SECRET_ACCESS_KEY}"

# Endpoint: explícito (R2_ENDPOINT) o derivado del account id.
if [ -z "${R2_ENDPOINT:-}" ]; then
  : "${R2_ACCOUNT_ID:?falta R2_ENDPOINT o R2_ACCOUNT_ID}"
  R2_ENDPOINT="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
fi

# aws-cli lee las credenciales del entorno; R2 exige la región 'auto'.
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="auto"

# Mapea un componente lógico a pares "prefijo_r2 dir_local" (uno por línea).
# El "corpus crudo" (lo que reutiliza run_all --skip-scrape --skip-download) es
# la unión de ifop + registry + vms + copernicus.
r2_paths() {
  case "$1" in
    ifop)       echo "raw/ifop/raw data/processing/ifop/raw" ;;
    registry)   echo "raw/registry/raw data/processing/registry/raw"
                echo "raw/registry/fishing_types data/processing/registry/fishing_types" ;;
    vms)        echo "raw/locations/raw_daily data/processing/locations/raw_daily" ;;
    copernicus) echo "raw/copernicus data/copernicus" ;;
    output)     echo "output data/output" ;;
    raw)        r2_paths ifop; r2_paths registry; r2_paths vms; r2_paths copernicus ;;
    *) echo "componente desconocido: $1 (usa: ifop|registry|vms|copernicus|raw|output)" >&2; return 1 ;;
  esac
}

# r2_sync <origen> <destino> : sync recursivo silencioso (solo errores).
r2_sync() {
  aws s3 sync "$1" "$2" --endpoint-url "$R2_ENDPOINT" --only-show-errors
}
