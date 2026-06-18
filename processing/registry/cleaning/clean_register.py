"""
Preprocesa data/processing/registry/input/register.csv: deja sólo embarcaciones
de categoría LANCHA y, para cada combinación (Nº Matrícula, Puerto), conserva la
inscripción más reciente según `Fecha Inscripción`. El resultado se escribe en
data/processing/registry/register_clean.csv.

El registro histórico añade una nueva fila cada vez que una embarcación
cambia de armador (con un nuevo `Nº RPA`); la matrícula del puerto en
cambio se mantiene. Para que el RPA exportado sea el que aparece en los
reportes VMS de Sernapesca, se conserva la fila con la fecha de
inscripción más reciente.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
REGISTRY_DIR = DATA_DIR / "processing" / "registry"
INPUT_CSV = REGISTRY_DIR / "input" / "register.csv"
OUTPUT_CSV = REGISTRY_DIR / "register_clean.csv"

CATEGORIA_VALUE = "LANCHA"
DEDUP_KEYS = ["Nº Matrícula", "Puerto"]
FECHA_COL = "Fecha Inscripción"
CATEGORIA_COL = "Categoría"

REQUIRED_COLS = [
    "Nº RPA",
    "Nombre Embarcación",
    CATEGORIA_COL,
    FECHA_COL,
    *DEDUP_KEYS,
]


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verifica que el registro histórico esté en\n"
            "       data/processing/registry/input/register.csv.",
            file=sys.stderr,
        )
        sys.exit(2)

    # El archivo usa ';' como separador (no ',').
    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, encoding="utf-8")

    faltantes = [c for c in REQUIRED_COLS if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {faltantes}.",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(df)

    lanchas = df[df[CATEGORIA_COL] == CATEGORIA_VALUE].copy()
    if lanchas.empty:
        print(
            f"ERROR: el filtro no produjo filas. Revisa que la categoría\n"
            f"       '{CATEGORIA_VALUE}' siga apareciendo en el CSV.",
            file=sys.stderr,
        )
        sys.exit(1)

    lanchas["_fecha_dt"] = pd.to_datetime(
        lanchas[FECHA_COL], format="%d-%m-%Y", errors="coerce"
    )
    n_fecha_invalida = int(lanchas["_fecha_dt"].isna().sum())
    lanchas = lanchas.dropna(subset=["_fecha_dt"])

    lanchas = lanchas.sort_values("_fecha_dt", ascending=False)
    n_antes_dedup = len(lanchas)
    lanchas = lanchas.drop_duplicates(subset=DEDUP_KEYS, keep="first")
    n_eliminadas_dup = n_antes_dedup - len(lanchas)

    lanchas = lanchas.drop(columns="_fecha_dt")
    lanchas.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas totales:                  {total:,}\n"
        f"Filas LANCHA:                   {n_antes_dedup + n_fecha_invalida:,} "
        f"(Categoría='{CATEGORIA_VALUE}')\n"
        f"Filas con fecha inválida:       {n_fecha_invalida:,} "
        f"(Fecha Inscripción no parseable como DD-MM-YYYY)\n"
        f"Filas eliminadas por duplicado: {n_eliminadas_dup:,} "
        f"(misma {DEDUP_KEYS[0]} y {DEDUP_KEYS[1]}, se conserva la más reciente)\n"
        f"Filas finales:                  {len(lanchas):,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
