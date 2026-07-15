"""
Construye el dataset de zarpes con captura tomando como ESPINA la captura
filtrada de la bitácora (`capture.csv`): cada recalada de jurel en el/los
puerto(s) de interés (Caldera) es un zarpe, enriquecido con el nombre de la
embarcación desde IFOP.

Antes la espina eran los viajes observados de IFOP (`zarpes_atacama.csv`) y la
captura se unía por inner join al minuto: como IFOP solo observa una MUESTRA de
los viajes, el cruce caía a ~80 zarpes. La bitácora, en cambio, registra TODAS
las recaladas, así que usarla como espina multiplica ~30x los zarpes con captura.
El costo es que la bitácora no trae ni hora de zarpe ni nº de lances: la ventana
del viaje se reconstruye aguas abajo desde la traza VMS (`identify_zarpes.py`) y
ya no se filtra por nº de lances.

El puente con IFOP sigue siendo la identidad determinista de la embarcación
  COD_BARCO = HEX(vessel_code + 5)
(ver data/bitacora/ifop_cod_barco_README.md): la limpieza ya dejó `vessel_code`
en `capture.csv`, así que `vessel_name` se anexa por `vessel_code` (left join)
contra la tabla de embarcaciones de IFOP. Las recaladas de barcos ausentes del
SIEM quedan con `vessel_name` nulo pero NO se descartan.

El `zarpe_id` correlativo (1..N) se asigna acá y es el id que arrastran todas las
etapas aguas abajo (asignación de pings VMS y ubicación del lance).

Entradas:
  data/processing/capture/capture.csv        (espina: captura filtrada, con vessel_code)
  data/processing/ifop/vessels.csv           (para anexar vessel_name)

Salida:
  data/processing/capture/zarpes_atacama_capture.csv

Uso:
    uv run python -m processing.capture.unify.unify_zarpes
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.datasets import active_source
from processing.utils.species import ALL_SPECIES, SPECIES_OF_INTEREST
from processing.utils.species_scope import active_species_scope


DATA_DIR    = Path(__file__).resolve().parents[3] / "data"
VESSELS_CSV = DATA_DIR / "processing" / "ifop" / "vessels.csv"

# Columnas base (siempre presentes); las columnas de captura por especie se
# insertan dinámicamente entre `landing_port` y `principal_catch` según qué
# especies traiga la captura filtrada (una en `jurel`, todas en `all`).
BASE_COLS = [
    "zarpe_id", "vessel_code", "vessel_name", "cod_barco",
    "landing_datetime", "landing_port",
]


def _species_col(species: str) -> str:
    """Nombre de columna de captura por especie (p.ej. JACK_MACKEREL → jack_mackerel_tons)."""
    return f"{species.lower()}_tons"


def construir(capture: pd.DataFrame, vessels: pd.DataFrame) -> pd.DataFrame:
    """Captura filtrada → zarpes con captura (1 fila por recalada) + zarpe_id."""
    c = capture.copy()
    c["vessel_code"] = c["vessel_code"].astype(str).str.strip()
    c["_land"] = pd.to_datetime(c["LANDING_DATETIME"], errors="coerce")

    # Orden cronológico estable (por recalada, desempate por barco) antes del id.
    c = c.sort_values(["_land", "vessel_code"], kind="stable").reset_index(drop=True)

    # vessel_name desde la tabla de embarcaciones IFOP (cruce por vessel_code).
    vn = vessels[["vessel_code", "vessel_name"]].copy()
    vn["vessel_code"] = vn["vessel_code"].astype(str).str.strip()
    vn = vn.drop_duplicates(subset=["vessel_code"], keep="first")

    # Columnas de especie presentes en la captura (jurel siempre primero, luego el
    # resto en el orden de ALL_SPECIES). En `jurel` solo estará JACK_MACKEREL.
    especies = [SPECIES_OF_INTEREST] + [
        s for s in ALL_SPECIES if s != SPECIES_OF_INTEREST
    ]
    especies = [s for s in especies if s in c.columns]

    datos = {
        "vessel_code":      c["vessel_code"],
        "cod_barco":        c["COD_BARCO"],
        "landing_datetime": c["LANDING_DATETIME"],
        "landing_port":     c["PORT"],
    }
    for s in especies:
        datos[_species_col(s)] = c[s]
    datos["principal_catch"] = c["PRINCIPAL_CATCH"]

    out = pd.DataFrame(datos)
    out = out.merge(vn, on="vessel_code", how="left")
    out.insert(0, "zarpe_id", range(1, len(out) + 1))

    cols = BASE_COLS + [_species_col(s) for s in especies] + ["principal_catch"]
    return out[cols]


def main() -> None:
    # Rutas scopeadas por fuente (SOURCE) y alcance de especies (SPECIES_SCOPE):
    # `backup` anida bajo capture/backup/, `all` bajo …/all_species/.
    capture_dir = active_species_scope().scoped(
        active_source().scoped(DATA_DIR / "processing" / "capture")
    )
    CAPTURE_CSV = capture_dir / "capture.csv"
    OUTPUT_DIR  = capture_dir
    OUTPUT_CSV  = OUTPUT_DIR / "zarpes_atacama_capture.csv"

    for ruta, pista in (
        (CAPTURE_CSV, "uv run python -m processing.capture.filter.filter_capture"),
        (VESSELS_CSV, "uv run python -m processing.ifop.identifiers.extract_vessels"),
    ):
        if not ruta.exists():
            print(
                f"ERROR: no existe {ruta}.\n"
                f"       Generalo primero con:\n           {pista}",
                file=sys.stderr,
            )
            sys.exit(1)

    capture = pd.read_csv(CAPTURE_CSV, sep=";", dtype=str)
    vessels = pd.read_csv(VESSELS_CSV, dtype=str)

    zarpes = construir(capture, vessels)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zarpes.to_csv(OUTPUT_CSV, index=False)

    n = len(zarpes)
    sin_nombre = int(zarpes["vessel_name"].isna().sum())
    print(
        f"Zarpes con captura (espina = bitácora): {n:,}\n"
        f"  sin vessel_name (ausentes del SIEM):  {sin_nombre:,}\n"
        f"Archivo escrito:                        {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
