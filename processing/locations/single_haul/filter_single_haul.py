"""
Recorta el producto de localizaciones a los zarpes con UN SOLO lance CONFIABLE,
el conjunto limpio para el modelado: la captura del viaje (por zarpe) se mapea sin
ambigüedad a una única ubicación de pesca de alta confianza.

Criterio (dos condiciones, sobre `zarpes_atacama_haul_location.csv`):
  - `haul_confidence == "alta"` — el lance representativo es un anillo circular del
    cerco (no un mero tramo lento mar adentro).
  - `n_hauls == 1` — el viaje tiene exactamente un lance confiable, así que la
    captura del zarpe corresponde inequívocamente a ese lance.

Sucede al antiguo `filter_single_haul` que cruzaba el `num_hauls` declarado por
IFOP; ahora el nº de lances se deriva de la propia traza VMS (geometría circular
en `identify_fishing_location.py`), no de la bitácora.

Entrada:
  data/processing/locations/fishing_location/zarpes_atacama_haul_location.csv

Salida:
  data/processing/locations/single_haul/zarpes_atacama_haul_single.csv
      → (PRODUCTO) misma estructura que la entrada, solo los zarpes de un único
        lance confiable (modeling-ready).

Uso:
    uv run python -m processing.locations.single_haul.filter_single_haul
"""

import sys
from pathlib import Path

import pandas as pd


LOCATIONS_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
OUTPUT_DIR = LOCATIONS_DIR / "single_haul"
HAUL_CSV = LOCATIONS_DIR / "fishing_location" / "zarpes_atacama_haul_location.csv"
SINGLE_CSV = OUTPUT_DIR / "zarpes_atacama_haul_single.csv"

# Condiciones del conjunto limpio.
CONFIDENCE = "alta"
N_HAULS = 1


def filtrar(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve los zarpes con un único lance confiable (`alta` + `n_hauls == 1`)."""
    n_hauls = pd.to_numeric(df["n_hauls"], errors="coerce")
    mask = (df["haul_confidence"].astype(str).str.strip() == CONFIDENCE) & (n_hauls == N_HAULS)
    return df[mask].copy()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    if not HAUL_CSV.exists():
        print(
            f"ERROR: no existe {HAUL_CSV}.\n"
            "       Generá la ubicación del lance primero con:\n"
            "           uv run python -m processing.locations.fishing_location.identify_fishing_location",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(HAUL_CSV)
    single = filtrar(df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    single.to_csv(SINGLE_CSV, index=False)

    print(
        f"Filtrando zarpes de un único lance confiable "
        f"(haul_confidence == \"{CONFIDENCE}\" y n_hauls == {N_HAULS})\n"
        f"  Entrada: {HAUL_CSV}\n\n"
        f"Zarpes de entrada:           {len(df):,}\n"
        f"  con un lance confiable:    {len(single):,}\n"
        f"  descartados:               {len(df) - len(single):,}\n"
        f"Archivo escrito:\n"
        f"  {SINGLE_CSV}"
    )


if __name__ == "__main__":
    main()
