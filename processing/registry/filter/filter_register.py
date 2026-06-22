"""
Filtrado del registro de embarcaciones (paso 2 del pipeline registry).

Lee la salida del recorte por región
(data/processing/registry/region_scoped/register.csv) y conserva únicamente las
embarcaciones de categoría LANCHA, que son la clase de tamaño relevante para el
análisis de la flota artesanal. El resultado se escribe en
data/processing/registry/filtered/register.csv.

Las etapas previas (clean_register → filter_region_scope) ya renombraron las
columnas a inglés, normalizaron las fechas, deduplicaron y recortaron a la región
activa; aquí solo se filtra por categoría.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_DIR = DATA_DIR / "processing" / "registry"
INPUT_CSV = REGISTRY_DIR / "region_scoped" / "register.csv"
OUTPUT_CSV = REGISTRY_DIR / "filtered" / "register.csv"

CATEGORY_COL = "category"
CATEGORY_VALUE = "LANCHA"


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Ejecutá primero: uv run python -m "
            "processing.registry.region_filter.filter_region_scope",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, encoding="utf-8")

    if CATEGORY_COL not in df.columns:
        print(
            f"ERROR: falta la columna '{CATEGORY_COL}' en {INPUT_CSV}.\n"
            "       ¿Cambió el esquema del paso de limpieza?",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(df)
    lanchas = df[df[CATEGORY_COL] == CATEGORY_VALUE].copy()

    if lanchas.empty:
        print(
            f"ERROR: el filtro no produjo filas. Revisa que la categoría\n"
            f"       '{CATEGORY_VALUE}' siga apareciendo en la columna "
            f"'{CATEGORY_COL}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    lanchas.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas totales:    {total:,}\n"
        f"Filas {CATEGORY_VALUE}:    {len(lanchas):,} "
        f"({CATEGORY_COL} = '{CATEGORY_VALUE}')\n"
        f"Filas descartadas: {total - len(lanchas):,}\n"
        f"Archivo escrito:  {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
