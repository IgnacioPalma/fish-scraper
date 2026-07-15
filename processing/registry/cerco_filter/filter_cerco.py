"""
Filtro final del pipeline registry: flota de cerco con señal de llamada.

Lee data/processing/registry/fishing_types/register.csv y conserva las
embarcaciones que cumplen AMBAS condiciones:

  - su ÚNICO arte de captura es CERCO para TODAS sus especies (cerco exclusivo
    sobre toda la autorización: no usan enmalle, espinel ni línea de mano para
    ninguna especie), y
  - tienen señal de llamada (`signal_code` no vacío).

El cerco exclusivo se juzga sobre la UNIÓN de los artes de todas las especies de
`species_fishing_types` (`ESPECIE:id[,id]|…`), no solo sobre el jurel. El id de
CERCO se lee del catálogo fishing_types.csv (no se fija a mano). La salida es el
producto final del registro: data/processing/registry/register.csv, con las
mismas columnas que la entrada.
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

    # Unión de ids de arte sobre TODAS las especies de `species_fishing_types`
    # ('ESPECIE:id[,id]|…'); cerco exclusivo == {cerco_id}.
    def _union_ids(cell: str) -> set[str]:
        ids: set[str] = set()
        for bloque in cell.split("|"):
            if ":" not in bloque:
                continue
            _, arte_ids = bloque.split(":", 1)
            ids |= {i for i in arte_ids.split(",") if i}
        return ids

    ids = df["species_fishing_types"].apply(_union_ids)
    cerco_exclusivo = ids.apply(lambda s: s == {cerco_id})
    con_senal = df["signal_code"] != ""

    filtrado = df[cerco_exclusivo & con_senal].copy()

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    filtrado.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Embarcaciones (fishing_types):  {total:,}\n"
        f"Cerco exclusivo (toda especie): {int(cerco_exclusivo.sum()):,} "
        f"(unión de artes == '{cerco_id}')\n"
        f"  …además con señal de llamada: {len(filtrado):,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
