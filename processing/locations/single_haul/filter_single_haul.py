"""
Arma el CONJUNTO DE MODELADO a partir del producto de localizaciones: todos los
zarpes con una ubicación de lance utilizable, con un peso por ejemplo que refleja
la calidad de esa ubicación.

Antes esta etapa recortaba al conjunto ESTRICTO (`haul_confidence == "alta"` y
`n_hauls == 1`), pensado para mapear la captura del viaje a UNA única ubicación sin
ambigüedad. Ese recorte descartaba la mayoría de los zarpes localizados (los de
confianza `baja` y los viajes con >1 lance), lo que dejaba muy pocos ejemplos para
entrenar y favorecía el sobreajuste. Ahora se conservan TODOS los zarpes con
ubicación y se expone la calidad como columnas, para que el modelo decida cómo
usarlos (pesos, filtros, o quedarse solo con el subconjunto estricto).

Criterio (sobre `zarpes_atacama_haul_location.csv`):
  - Se CONSERVAN los zarpes con `haul_confidence in {"alta", "baja"}` — es decir,
    los que tienen una ubicación de lance (`haul_lat`/`haul_lon` no vacíos).
  - Se DESCARTAN solo los `haul_confidence == "sin_pesca"` (sin ningún tramo lento
    mar adentro → sin ubicación que muestrear).

Columnas que agrega (pasan tal cual al dataset final `zarpes_<region>_haul_env.csv`):
  - `sample_weight`: peso por ejemplo según la confianza de la ubicación
    (`alta` → `ALTA_WEIGHT`, `baja` → `BAJA_WEIGHT`). Es un punto de partida
    razonable y AJUSTABLE; para un modelo de captura conviene además bajar el peso
    de los viajes multi-lance (la captura del zarpe se reparte entre varios lances),
    lo que se puede hacer con `n_hauls` (que queda expuesto).
  - `is_single_haul`: booleano, `True` sii `alta` y `n_hauls == 1` — reproduce el
    antiguo conjunto estricto con un solo filtro (útil para un modelo de captura que
    exija atribución inequívoca captura→ubicación).

Sucede al antiguo `filter_single_haul` que cruzaba el `num_hauls` de IFOP; el nº de
lances se deriva de la propia traza VMS (geometría circular en
`identify_fishing_location.py`), no de la bitácora.

Entrada:
  data/processing/locations/fishing_location/zarpes_atacama_haul_location.csv

Salida:
  data/processing/locations/single_haul/zarpes_atacama_haul_single.csv
      → (PRODUCTO) misma estructura que la entrada + `sample_weight` e
        `is_single_haul`; todos los zarpes con ubicación (modeling-ready).

Uso:
    uv run python -m processing.locations.single_haul.filter_single_haul
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.datasets import active_source
from processing.utils.species_scope import active_species_scope


LOCATIONS_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"

# Confianzas con ubicación utilizable (las que NO son "sin_pesca").
LOCATED_CONFIDENCES = ("alta", "baja")

# Pesos por ejemplo según la confianza de la ubicación. Punto de partida ajustable:
# `alta` = anillo circular nítido (ubicación de calidad); `baja` = solo tramo lento
# mar adentro (ubicación más ruidosa) → menos peso.
ALTA_WEIGHT = 1.0
BAJA_WEIGHT = 0.5


def construir_conjunto(df: pd.DataFrame) -> pd.DataFrame:
    """Conserva los zarpes con ubicación y agrega `sample_weight` e `is_single_haul`."""
    confidence = df["haul_confidence"].astype(str).str.strip()
    located = df[confidence.isin(LOCATED_CONFIDENCES)].copy()

    conf = located["haul_confidence"].astype(str).str.strip()
    n_hauls = pd.to_numeric(located["n_hauls"], errors="coerce")

    located["sample_weight"] = conf.map({"alta": ALTA_WEIGHT, "baja": BAJA_WEIGHT})
    located["is_single_haul"] = (conf == "alta") & (n_hauls == 1)
    return located


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    # Entrada/salida scopeadas por fuente (SOURCE) y alcance de especies
    # (SPECIES_SCOPE): `backup` anida bajo locations/backup/, `all` bajo
    # …/all_species/.
    source_dir = active_species_scope().scoped(active_source().scoped(LOCATIONS_DIR))
    HAUL_CSV = source_dir / "fishing_location" / "zarpes_atacama_haul_location.csv"
    OUTPUT_DIR = source_dir / "single_haul"
    SINGLE_CSV = OUTPUT_DIR / "zarpes_atacama_haul_single.csv"

    if not HAUL_CSV.exists():
        print(
            f"ERROR: no existe {HAUL_CSV}.\n"
            "       Generá la ubicación del lance primero con:\n"
            "           uv run python -m processing.locations.fishing_location.identify_fishing_location",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(HAUL_CSV)
    modelado = construir_conjunto(df)

    n_single = int(modelado["is_single_haul"].sum())
    n_alta = int((modelado["haul_confidence"].astype(str).str.strip() == "alta").sum())
    n_baja = int((modelado["haul_confidence"].astype(str).str.strip() == "baja").sum())

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    modelado.to_csv(SINGLE_CSV, index=False)

    print(
        f"Conjunto de modelado (zarpes con ubicación: haul_confidence in "
        f"{list(LOCATED_CONFIDENCES)})\n"
        f"  Entrada: {HAUL_CSV}\n\n"
        f"Zarpes de entrada:              {len(df):,}\n"
        f"  con ubicación (conservados):  {len(modelado):,}\n"
        f"    confianza alta (peso {ALTA_WEIGHT}):  {n_alta:,}\n"
        f"    confianza baja (peso {BAJA_WEIGHT}):  {n_baja:,}\n"
        f"  descartados (sin_pesca):      {len(df) - len(modelado):,}\n"
        f"  de esos, un único lance confiable (is_single_haul): {n_single:,}\n"
        f"Archivo escrito:\n"
        f"  {SINGLE_CSV}"
    )


if __name__ == "__main__":
    main()
