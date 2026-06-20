"""
Construye la tabla de zarpes (viajes/recaladas) a partir de los viajes IFOP
limpios (`clean_viajes.py`).

Un zarpe es un evento de salida-recalada de una embarcación. Esta tabla es la
proyección de los viajes sobre las columnas que definen el viaje en sí (no al
observador ni al muestreo), referenciando las tablas de identificadores:

  departure_datetime   zarpe (ISO 8601)
  arrival_datetime     recalada (ISO 8601)
  vessel_code          → vessels.csv
  departure_port_id    → ports.csv
  arrival_port_id      → ports.csv
  target_species_id    → species.csv
  num_hauls            número de lances del viaje

Se deduplica porque un mismo zarpe puede quedar registrado por dos observadores
embarcados en el mismo barco: ambos describen el mismo viaje, así que colapsan a
una fila. Se descartan las filas sin embarcación ni fecha de zarpe (no
identifican un viaje).

Entrada:
  data/processing/ifop/cleaned/ifop_cleaned.csv

Salida:
  data/processing/ifop/zarpes.csv

Uso:
    uv run python -m processing.ifop.identifiers.extract_zarpes
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV  = DATA_DIR / "processing" / "ifop" / "cleaned" / "ifop_cleaned.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "ifop" / "zarpes.csv"

# Columnas que definen el zarpe (proyección de los viajes limpios).
COLS_ZARPE = [
    "departure_datetime", "arrival_datetime",
    "vessel_code",
    "departure_port_id", "arrival_port_id",
    "target_species_id",
    "num_hauls",
]


def extraer_zarpes(df: pd.DataFrame) -> pd.DataFrame:
    """Proyecta los viajes a las columnas del zarpe, deduplicado."""
    zarpes = (df[COLS_ZARPE]
                .dropna(subset=["vessel_code", "departure_datetime"], how="all")
                .drop_duplicates())

    return zarpes.sort_values(["departure_datetime", "vessel_code"]) \
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

    faltantes = [c for c in COLS_ZARPE if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: al CSV limpio le faltan columnas esperadas: {faltantes}.\n"
            "       ¿Quedó desactualizado clean_viajes.py?",
            file=sys.stderr,
        )
        sys.exit(1)

    zarpes = extraer_zarpes(df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    zarpes.to_csv(OUTPUT_CSV, index=False)

    print(f"Zarpes únicos: {len(zarpes)} (de {len(df)} viajes limpios).")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
