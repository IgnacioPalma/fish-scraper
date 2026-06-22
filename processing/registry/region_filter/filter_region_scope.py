"""
Recorte del registro nacional a la región activa (paso 1.5 del pipeline registry).

Lee la salida de la limpieza (data/processing/registry/cleaned/register.csv, que
ya es NACIONAL gracias al scraper de la etapa 0) y conserva solo las embarcaciones
cuya `region` está en el perfil de región activo
(processing/utils/regions.py → registry_region_codes; lo elige la variable de
entorno REGION). El resultado se escribe en
data/processing/registry/region_scoped/register.csv.

Corre ANTES del filtro por categoría y, sobre todo, antes del scraping por RPA de
la etapa `fishing_types` (lento), de modo que la consulta cara por embarcación
quede acotada a la región del proyecto.

  - REGION=atacama → conserva solo "III REGION" (reproduce el alcance histórico).
  - REGION=chile   → no-op (todas las regiones costeras).

Uso:
    uv run python -m processing.registry.region_filter.filter_region_scope
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.regions import active_region

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_DIR = DATA_DIR / "processing" / "registry"
INPUT_CSV = REGISTRY_DIR / "cleaned" / "register.csv"
OUTPUT_CSV = REGISTRY_DIR / "region_scoped" / "register.csv"

REGION_COL = "region"


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Ejecutá primero: uv run python -m processing.registry.cleaning.clean_register",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, encoding="utf-8")

    if REGION_COL not in df.columns:
        print(
            f"ERROR: falta la columna '{REGION_COL}' en {INPUT_CSV}.\n"
            "       Regenerá el registro nacional con el scraper de la etapa 0\n"
            "       (processing.registry.scraper.scrape_registry), que la agrega.",
            file=sys.stderr,
        )
        sys.exit(2)

    region = active_region()
    codigos = region.registry_region_codes
    if not codigos:
        print(
            f"ERROR: la región '{region.key}' no define registry_region_codes en "
            f"processing/utils/regions.py.",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(df)
    scoped = df[df[REGION_COL].isin(codigos)].copy()

    if scoped.empty:
        print(
            f"ERROR: ninguna embarcación en regiones {list(codigos)}.\n"
            f"       Valores presentes: {sorted(df[REGION_COL].dropna().unique())}.",
            file=sys.stderr,
        )
        sys.exit(1)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    scoped.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Región activa:     {region.key}  → {list(codigos)}\n"
        f"Filas totales:     {total:,}\n"
        f"Filas en región:   {len(scoped):,}\n"
        f"Filas descartadas: {total - len(scoped):,}\n"
        f"Archivo escrito:   {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
