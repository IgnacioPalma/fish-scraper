"""
Une los zarpes de referencia de IFOP (`zarpes_atacama.csv`) con la captura
filtrada de la bitácora (`capture.csv`) en una sola tabla analítica: cada zarpe
observado enriquecido con la captura de jurel declarada en su recalada.

El puente entre ambas fuentes es la identidad determinista de la embarcación
  COD_BARCO = HEX(vessel_code + 5)
(ver data/bitacora/ifop_cod_barco_README.md). La etapa de limpieza ya dejó
`vessel_code` en `capture.csv`, así que el cruce es por `vessel_code` + la marca
de tiempo de recalada (arrival_datetime ↔ landing_datetime) a resolución de
minuto. Se hace un INNER JOIN: solo quedan los zarpes que tienen captura.

Empíricamente el cruce es exacto cuando existe (ampliar la tolerancia no agrega
coincidencias), por eso `TOL_MIN = 0` (igualdad al minuto). El resto de los
zarpes de `zarpes_atacama.csv` no tiene captura porque la captura está acotada al
alcance del estudio (Caldera + jurel + rango de fechas global).

Entradas:
  data/processing/ifop/zarpes_atacama.csv   (spine: zarpes de referencia)
  data/processing/capture/capture.csv        (captura filtrada, con vessel_code)
  data/processing/ifop/vessels.csv           (para anexar vessel_name)

Salida:
  data/output/zarpes_atacama_capture.csv

Uso:
    uv run python -m processing.capture.unify.unify_zarpes
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR    = Path(__file__).resolve().parents[3] / "data"
ZARPES_CSV  = DATA_DIR / "processing" / "ifop" / "zarpes_atacama.csv"
CAPTURE_CSV = DATA_DIR / "processing" / "capture" / "capture.csv"
VESSELS_CSV = DATA_DIR / "processing" / "ifop" / "vessels.csv"
OUTPUT_DIR  = DATA_DIR / "output"
OUTPUT_CSV  = OUTPUT_DIR / "zarpes_atacama_capture.csv"

# Tolerancia del cruce temporal, en minutos. 0 = igualdad al minuto. El cruce es
# exacto cuando existe; ampliar la tolerancia no agrega coincidencias (probado).
TOL_MIN = 0

# Columnas del zarpe (spine) que se conservan tal cual.
ZARPE_COLS = [
    "zarpe_id", "departure_datetime", "arrival_datetime", "vessel_code",
    "departure_port_id", "arrival_port_id", "target_species_id", "num_hauls",
]


def _clave_minuto(vessel_code: pd.Series, dt: pd.Series) -> pd.Series:
    """Llave de cruce: vessel_code + marca de tiempo truncada al minuto."""
    return (vessel_code.astype(str).str.strip() + "|"
            + dt.dt.strftime("%Y-%m-%d %H:%M"))


def unir(zarpes: pd.DataFrame, capture: pd.DataFrame,
         vessels: pd.DataFrame) -> pd.DataFrame:
    """INNER JOIN zarpes ↔ captura por (vessel_code, recalada al minuto)."""
    z = zarpes.copy()
    z["_arr"] = pd.to_datetime(z["arrival_datetime"], errors="coerce")
    z["_key"] = _clave_minuto(z["vessel_code"], z["_arr"])

    c = capture.copy()
    c["_land"] = pd.to_datetime(c["LANDING_DATETIME"], errors="coerce")
    c["_key"] = _clave_minuto(c["vessel_code"], c["_land"])

    # Captura → columnas de salida (nombres en minúscula, prefijo de recalada).
    cap = pd.DataFrame({
        "_key":            c["_key"],
        "cod_barco":       c["COD_BARCO"],
        "landing_datetime": c["LANDING_DATETIME"],
        "landing_port":    c["PORT"],
        "jack_mackerel_kg": c["JACK_MACKEREL"],
        "principal_catch": c["PRINCIPAL_CATCH"],
    })
    # Defensa: una sola fila de captura por llave (hoy no hay duplicados).
    cap = cap.dropna(subset=["_key"]).drop_duplicates(subset=["_key"], keep="first")

    # vessel_name desde la tabla de embarcaciones IFOP (cruce por vessel_code).
    vn = vessels[["vessel_code", "vessel_name"]].copy()
    vn["vessel_code"] = vn["vessel_code"].astype(str).str.strip()

    unido = (z.merge(cap, on="_key", how="inner")
              .merge(vn, on="vessel_code", how="left"))

    cols = ZARPE_COLS + ["vessel_name", "cod_barco", "landing_datetime",
                         "landing_port", "jack_mackerel_kg", "principal_catch"]
    return unido[cols].sort_values("zarpe_id").reset_index(drop=True)


def main() -> None:
    for ruta, pista in (
        (ZARPES_CSV, "uv run python -m processing.ifop.filter.filter_zarpes"),
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

    zarpes  = pd.read_csv(ZARPES_CSV, dtype=str)
    capture = pd.read_csv(CAPTURE_CSV, sep=";", dtype=str)
    vessels = pd.read_csv(VESSELS_CSV, dtype=str)

    unido = unir(zarpes, capture, vessels)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    unido.to_csv(OUTPUT_CSV, index=False)

    n_zarpes = len(zarpes)
    n_match  = len(unido)
    pct = 100 * n_match / n_zarpes if n_zarpes else 0.0
    print(
        f"Zarpes de referencia (Atacama):  {n_zarpes:,}\n"
        f"Zarpes con captura (inner join): {n_match:,}  ({pct:.1f}%)\n"
        f"Archivo escrito:                 {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
