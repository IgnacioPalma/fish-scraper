"""
Filtra data/ships.csv a los lances de la flota Artesanal en la Región de
Atacama y exporta el resultado a data/ships_filtered.csv.

El CSV de entrada usa ';' como separador y contiene ~93k filas; el filtro
resulta en ~11.5k filas.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_CSV = DATA_DIR / "ships.csv"
OUTPUT_CSV = DATA_DIR / "ships_filtered.csv"

REGION_VALUE = "Región de Atacama"
FLOTA_VALUE = "Artesanal"


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verifica que el archivo de lances esté en data/ships.csv.",
            file=sys.stderr,
        )
        sys.exit(2)

    # El archivo usa ';' como separador (no ',').
    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, low_memory=False)

    faltantes = {"REGION", "FLOTA"} - set(df.columns)
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {sorted(faltantes)}.",
            file=sys.stderr,
        )
        sys.exit(2)

    filtrado = df[(df["REGION"] == REGION_VALUE) & (df["FLOTA"] == FLOTA_VALUE)]

    if filtrado.empty:
        print(
            "ERROR: el filtro no produjo filas. Revisa que los valores\n"
            f"       REGION='{REGION_VALUE}' y FLOTA='{FLOTA_VALUE}' aún existan.",
            file=sys.stderr,
        )
        sys.exit(1)

    filtrado.to_csv(OUTPUT_CSV, sep=";", index=False)

    print(
        f"Filas totales:    {len(df):,}\n"
        f"Filas filtradas:  {len(filtrado):,} "
        f"(REGION='{REGION_VALUE}', FLOTA='{FLOTA_VALUE}')\n"
        f"Archivo escrito:  {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
