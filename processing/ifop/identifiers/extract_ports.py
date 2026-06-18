"""
Construye la tabla de identificadores de puerto a partir de los viajes IFOP
limpios (`clean_viajes.py`).

Cada viaje trae un puerto de zarpe y uno de recalada, ambos ya separados en
`<id>` + `<nombre>`. Este script une los dos extremos, elimina duplicados y deja
una tabla mínima `port_id ↔ port_name` (una fila por puerto).

Entrada:
  data/processing/ifop/cleaned/ifop_cleaned.csv

Salida:
  data/processing/ifop/ports.csv   (port_id, port_name)

Uso:
    uv run python -m processing.ifop.identifiers.extract_ports
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV  = DATA_DIR / "processing" / "ifop" / "cleaned" / "ifop_cleaned.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "ifop" / "ports.csv"


def extraer_puertos(df: pd.DataFrame) -> pd.DataFrame:
    """Une puertos de zarpe y recalada en una tabla única id ↔ nombre."""
    zarpe = df[["departure_port_id", "departure_port_name"]].rename(
        columns={"departure_port_id": "port_id", "departure_port_name": "port_name"})
    recala = df[["arrival_port_id", "arrival_port_name"]].rename(
        columns={"arrival_port_id": "port_id", "arrival_port_name": "port_name"})

    puertos = (pd.concat([zarpe, recala], ignore_index=True)
                 .dropna(subset=["port_id"])
                 .drop_duplicates())

    # Un id con más de un nombre indicaría datos inconsistentes; se avisa pero no
    # se aborta (nos quedamos con todas las variantes para inspección).
    conflictos = puertos.groupby("port_id")["port_name"].nunique()
    conflictos = conflictos[conflictos > 1]
    if not conflictos.empty:
        print(f"AVISO: {len(conflictos)} id(s) de puerto con más de un nombre: "
              f"{list(conflictos.index)}", file=sys.stderr)

    return puertos.sort_values("port_id", key=lambda s: s.astype(int)) \
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
    puertos = extraer_puertos(df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    puertos.to_csv(OUTPUT_CSV, index=False)

    print(f"Puertos únicos: {len(puertos)}")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
