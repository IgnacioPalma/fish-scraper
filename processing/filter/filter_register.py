"""
Filtra data/processing/registry/register_clean.csv a las embarcaciones cuyo Nº RPA
aparece en data/bitacora/bitacora_caldera_jurel.csv.

El resultado se escribe a data/processing/registry/register_caldera_jurel.csv
preservando el separador (`;`) y todas las columnas del registro fuente.
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
BITACORA_CSV = DATA_DIR / "bitacora" / "bitacora_caldera_jurel.csv"
REGISTER_CSV = DATA_DIR / "processing" / "registry" / "register_clean.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "registry" / "register_caldera_jurel.csv"

BITACORA_RPA_COL = "RPA"
REGISTER_RPA_COL = "Nº RPA"


def main() -> None:
    for path in (BITACORA_CSV, REGISTER_CSV):
        if not path.exists():
            print(
                f"ERROR: no se encontró {path}.",
                file=sys.stderr,
            )
            sys.exit(2)

    bitacora = pd.read_csv(BITACORA_CSV, sep=";", usecols=[BITACORA_RPA_COL])
    if BITACORA_RPA_COL not in bitacora.columns:
        print(
            f"ERROR: la bitácora no tiene la columna '{BITACORA_RPA_COL}'.",
            file=sys.stderr,
        )
        sys.exit(2)

    rpas = set(bitacora[BITACORA_RPA_COL].dropna().astype(str))

    register = pd.read_csv(REGISTER_CSV, sep=";", dtype=str)
    if REGISTER_RPA_COL not in register.columns:
        print(
            f"ERROR: el registro no tiene la columna '{REGISTER_RPA_COL}'.",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(register)
    mask = register[REGISTER_RPA_COL].isin(rpas)
    filtered = register.loc[mask].copy()

    if filtered.empty:
        print(
            "ERROR: ningún RPA de la bitácora coincide con el registro.\n"
            "       Verificá que ambos archivos correspondan al mismo dataset.",
            file=sys.stderr,
        )
        sys.exit(1)

    rpas_bitacora = len(rpas)
    rpas_encontrados = filtered[REGISTER_RPA_COL].nunique()
    rpas_faltantes = rpas_bitacora - rpas_encontrados

    filtered.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas en registro fuente:       {total:,}\n"
        f"RPAs únicos en bitácora:        {rpas_bitacora:,}\n"
        f"RPAs encontrados en registro:   {rpas_encontrados:,}\n"
        f"RPAs sin coincidencia:          {rpas_faltantes:,}\n"
        f"Filas en registro filtrado:     {len(filtered):,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
