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


DATA_DIR    = Path(__file__).resolve().parents[3] / "data"
VESSELS_CSV = DATA_DIR / "processing" / "ifop" / "vessels.csv"

# Columnas de salida (orden final del dataset de zarpes con captura).
OUTPUT_COLS = [
    "zarpe_id", "vessel_code", "vessel_name", "cod_barco",
    "landing_datetime", "landing_port", "jack_mackerel_kg", "principal_catch",
]


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

    out = pd.DataFrame({
        "vessel_code":      c["vessel_code"],
        "cod_barco":        c["COD_BARCO"],
        "landing_datetime": c["LANDING_DATETIME"],
        "landing_port":     c["PORT"],
        "jack_mackerel_kg": c["JACK_MACKEREL"],
        "principal_catch":  c["PRINCIPAL_CATCH"],
    })
    out = out.merge(vn, on="vessel_code", how="left")
    out.insert(0, "zarpe_id", range(1, len(out) + 1))
    return out[OUTPUT_COLS]


def main() -> None:
    # Rutas scopeadas por fuente (SOURCE): `backup` anida bajo capture/backup/.
    capture_dir = active_source().scoped(DATA_DIR / "processing" / "capture")
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
