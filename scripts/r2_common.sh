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

# Alcance geográfico del proyecto (el mismo REGION que usa el código Python;
# ver processing/utils/regions.py). Solo el crudo de Copernicus (y los productos
# de `output`) se prefijan por región: vienen recortados al bbox, así que atacama
# y chile son datos distintos que sin el prefijo colisionarían en la misma clave.
# El resto del corpus crudo (ifop, registry, vms, capture) son scrapes NACIONALES
# idénticos entre regiones, así que cuelgan de raw/ sin el segmento de región — no
# tiene sentido duplicarlos por región.
# Se lee del entorno (en CI viene del workflow; local, del .env ya cargado arriba),
# por defecto 'atacama'. Se normaliza a minúsculas como en active_region().
R2_REGION="$(printf '%s' "${REGION:-atacama}" | tr '[:upper:]' '[:lower:]')"

# Mapea un componente lógico a pares "prefijo_r2 dir_local" (uno por línea).
# El "corpus crudo" (lo que reutiliza run_all --skip-scrape --skip-download) es
# la unión de ifop + registry + vms + capture + copernicus. El componente
# `capture` trae la bitácora IFOP manual (data/processing/capture/input/
# bitacora.csv), única entrada que no se scrapea ni descarga.
# Layout del bucket: todo el corpus cuelga de raw/; los componentes nacionales
# NO se anidan por región (raw/ifop, raw/registry, raw/locations, raw/capture) y
# solo copernicus se anida bajo la región (raw/<region>/copernicus).
r2_paths() {
  case "$1" in
    ifop)       echo "raw/ifop/raw data/processing/ifop/raw" ;;
    registry)   echo "raw/registry/raw data/processing/registry/raw"
                echo "raw/registry/fishing_types data/processing/registry/fishing_types" ;;
    vms)        echo "raw/locations/raw_daily data/processing/locations/raw_daily" ;;
    capture)    echo "raw/capture/input data/processing/capture/input" ;;
    copernicus) echo "raw/${R2_REGION}/copernicus data/copernicus" ;;
    # Igual que `copernicus` pero el pull baja SOLO las 4 grillas .nc que consume
    # el pipeline de cómputo (sst/chl/phy/bgc; ver r2_pull.sh y
    # processing/copernicus/sample_haul_environment.py). Excluye los .csv (export
    # legible, nadie los lee) y sla/wind (sin uso), que llenaban el disco del runner.
    copernicus-nc) echo "raw/${R2_REGION}/copernicus data/copernicus" ;;
    output)     echo "output/${R2_REGION} data/output" ;;
    raw)        r2_paths ifop; r2_paths registry; r2_paths vms; r2_paths capture; r2_paths copernicus ;;
    *) echo "componente desconocido: $1 (usa: ifop|registry|vms|capture|copernicus|raw|output)" >&2; return 1 ;;
  esac
}

# r2_sync <origen> <destino> [args aws…] : sync recursivo silencioso (solo
# errores). Los args extra se pasan tal cual a `aws s3 sync` (p.ej. filtros
# --exclude/--include para bajar solo un subconjunto de la carpeta).
r2_sync() {
  local src="$1" dst="$2"
  shift 2
  aws s3 sync "$src" "$dst" --endpoint-url "$R2_ENDPOINT" --only-show-errors "$@"
}
