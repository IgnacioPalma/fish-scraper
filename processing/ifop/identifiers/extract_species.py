"""
Construye la tabla de identificadores de especie a partir de los viajes IFOP
limpios (`clean_viajes.py`).

Cada viaje trae una especie objetivo ya separada en `<id>` + `<nombre>`
(`target_species_id` / `target_species_name`, de la ficha de detalle). Este
script elimina duplicados y deja una tabla mínima `species_id ↔ species_name`
(una fila por especie).

Entrada:
  data/processing/ifop/cleaned/ifop_cleaned.csv

Salida:
  data/processing/ifop/species.csv   (species_id, species_name)

Uso:
    uv run python -m processing.ifop.identifiers.extract_species
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV  = DATA_DIR / "processing" / "ifop" / "cleaned" / "ifop_cleaned.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "ifop" / "species.csv"


def extraer_especies(df: pd.DataFrame) -> pd.DataFrame:
    """Deja una tabla única id ↔ nombre de especie objetivo."""
    especies = (df[["target_species_id", "target_species_name"]]
                  .rename(columns={"target_species_id": "species_id",
                                   "target_species_name": "species_name"})
                  .dropna(subset=["species_id"])
                  .drop_duplicates())

    # Un id con más de un nombre indicaría datos inconsistentes; se avisa pero no
    # se aborta (nos quedamos con todas las variantes para inspección).
    conflictos = especies.groupby("species_id")["species_name"].nunique()
    conflictos = conflictos[conflictos > 1]
    if not conflictos.empty:
        print(f"AVISO: {len(conflictos)} id(s) de especie con más de un nombre: "
              f"{list(conflictos.index)}", file=sys.stderr)

    return especies.sort_values("species_id", key=lambda s: s.astype(int)) \
                   .reset_index(drop=True)


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no existe {INPUT_CSV}.\n"
            "       Generá los viajes limpios primero con:\n"
            "           uv run python -m processing.ifop.cleaning.clean_viajes",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(INPUT_CSV, dtype=str)
    especies = extraer_especies(df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    especies.to_csv(OUTPUT_CSV, index=False)

    print(f"Especies únicas: {len(especies)}")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
