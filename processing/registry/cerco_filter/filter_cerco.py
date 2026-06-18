"""
Filtro final del pipeline registry: flota de cerco con señal de llamada.

Lee data/processing/registry/fishing_types/register.csv y conserva las
embarcaciones que cumplen AMBAS condiciones:

  - su ÚNICO arte de captura de JUREL es CERCO (cerco exclusivo: no usan enmalle,
    espinel ni línea de mano para JUREL), y
  - tienen señal de llamada (`signal_code` no vacío).

El id de CERCO se lee del catálogo fishing_types.csv (no se fija a mano). La
salida es el producto final del registro: data/processing/registry/register.csv,
con las mismas columnas que la entrada.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_DIR = DATA_DIR / "processing" / "registry"
INPUT_CSV = REGISTRY_DIR / "fishing_types" / "register.csv"
LOOKUP_CSV = REGISTRY_DIR / "fishing_types" / "fishing_types.csv"
OUTPUT_CSV = REGISTRY_DIR / "register.csv"

CERCO_NAME = "CERCO"


def main() -> None:
    for ruta in (INPUT_CSV, LOOKUP_CSV):
        if not ruta.exists():
            print(
                f"ERROR: no se encontró {ruta}.\n"
                "       Ejecutá primero: uv run python -m "
                "processing.registry.fishing_types.scrape_fishing_types",
                file=sys.stderr,
            )
            sys.exit(2)

    lookup = pd.read_csv(LOOKUP_CSV, sep=";", dtype=str)
    fila_cerco = lookup[lookup["fishing_type"] == CERCO_NAME]
    if fila_cerco.empty:
        print(
            f"ERROR: '{CERCO_NAME}' no aparece en {LOOKUP_CSV}.",
            file=sys.stderr,
        )
        sys.exit(1)
    cerco_id = fila_cerco["fishing_type_id"].iloc[0]

    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str).fillna("")
    total = len(df)

    # Conjunto de ids de JUREL por fila; cerco exclusivo == {cerco_id}.
    ids = df["jurel_fishing_type_ids"].apply(lambda s: set(s.split("|")) - {""})
    cerco_exclusivo = ids.apply(lambda s: s == {cerco_id})
    con_senal = df["signal_code"] != ""

    filtrado = df[cerco_exclusivo & con_senal].copy()

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    filtrado.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Embarcaciones (fishing_types):  {total:,}\n"
        f"Cerco exclusivo:                {int(cerco_exclusivo.sum()):,} "
        f"(jurel_fishing_type_ids == '{cerco_id}')\n"
        f"  …además con señal de llamada: {len(filtrado):,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
