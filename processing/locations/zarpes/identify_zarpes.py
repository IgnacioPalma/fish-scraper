"""
Agrupa las posiciones VMS de la flota del registro (`filter_registry.py`) en
"zarpes" (viajes de pesca), para poder analizar la actividad a nivel de viaje
en vez de ping a ping.

Definición de zarpe (criterio "ventana hacia la recalada"):
  La referencia es el dataset de zarpes con captura
  (`data/output/zarpes_atacama_capture.csv`, espina = bitácora): cada zarpe trae
  `vessel_code` + `landing_datetime` (hora real de recalada), pero NO la hora de
  zarpe. El viaje se reconstruye desde la propia traza VMS: cada ping se asigna a
  la PRÓXIMA recalada de su MISMA embarcación (`vessel_code`), y el viaje queda
  acotado por la recalada anterior del mismo barco —`(recalada previa, recalada]`—
  con un tope de `MAX_TRIP_DAYS` para que un barco detenido en puerto durante
  semanas no absorba pings viejos. El `zarpe_id` resultante es el mismo de ese
  dataset, de modo que la traza VMS de un viaje queda enlazada a su captura.

  Como la referencia son solo los zarpes con captura, los pings que no caen dentro
  de ninguna ventana (barco en puerto fuera de tope, fuera de temporada, o sin
  zarpe con captura) se descartan. A cada zarpe se le anota, como contexto, el
  puerto más cercano a su primer y último ping.

Entrada:
  data/processing/locations/filtered/locations_flota_artesanal_<rango>_registry.csv
  data/output/zarpes_atacama_capture.csv   (zarpes con captura: vessel_code + recalada)
  coordenadas de puerto de la región activa (processing/utils/regions.py)

Salidas:
  data/processing/locations/zarpes/locations_flota_artesanal_<rango>_zarpes.csv
      → los pings asignados a un zarpe + dist_port_km, nearest_port, zarpe_id
  data/processing/locations/zarpes/zarpes_flota_artesanal_<rango>_summary.csv
      → una fila por zarpe (inicio/fin, duración, nº pings, distancia máx. a
        puerto, distancia recorrida, puerto de zarpe/recalada aproximados, etc.)

Uso:
    uv run python -m processing.locations.zarpes.identify_zarpes
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME
from processing.utils.regions import active_region


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
FILTERED_DIR = DATA_DIR / "filtered"
OUTPUT_DIR = DATA_DIR / "zarpes"
UNIFIED_ZARPES_CSV = DATA_DIR.parent.parent / "output" / "zarpes_atacama_capture.csv"

EARTH_RADIUS_KM = 6371.0

# Tope de duración del viaje (días): un ping se asigna a la próxima recalada de su
# barco solo si esa recalada cae dentro de esta ventana hacia adelante. Acota el
# inicio del viaje cuando no hay recalada previa cercana (barco detenido en puerto
# por largos períodos). Los viajes de cerco de jurel frente a Caldera son cortos.
MAX_TRIP_DAYS = 5


def _rango_tag() -> str:
    """Etiqueta de rango (`2023` o `2023_2024`), idéntica al resto del pipeline."""
    years = list(range(START_DATE.year, END_DATE.year + 1))
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"


def _haversine(lat1, lon1, lat2, lon2):
    """Distancia haversine en km. Acepta escalares o arrays de numpy."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _dist_a_puertos(lat, lon, ports):
    """Devuelve (dist_min_km, nombre_puerto_más_cercano) para cada ping."""
    lat = lat.to_numpy(dtype=float)
    lon = lon.to_numpy(dtype=float)
    dists = np.column_stack([
        _haversine(lat, lon, p["latitud"], p["longitud"]) for p in ports
    ])
    idx_min = np.argmin(dists, axis=1)
    dist_min = dists[np.arange(len(lat)), idx_min]
    nombres = np.array([p["nombre"] for p in ports])
    return dist_min, nombres[idx_min]


def _asignar_zarpe(df: pd.DataFrame, refs: pd.DataFrame) -> pd.DataFrame:
    """Asigna a cada ping el zarpe_id de la recalada que cierra su viaje.

    Cruce por `vessel_code` + ventana temporal hacia adelante: para cada ping se
    toma la recalada del mismo barco con el `landing_datetime` más próximo >=
    fecha del ping (merge_asof hacia adelante). El viaje queda acotado por la
    recalada ANTERIOR del mismo barco —el ping debe ser posterior a ella— y por
    `MAX_TRIP_DAYS` —la recalada no puede estar a más de ese tope hacia adelante—.
    Los pings que no caen en ninguna ventana quedan con zarpe_id nulo.
    """
    refs = refs[["zarpe_id", "vessel_code", "landing_datetime"]].copy()
    refs["vessel_code"] = refs["vessel_code"].astype(str).str.strip()
    refs["_arr"] = pd.to_datetime(refs["landing_datetime"], errors="coerce")
    refs = refs.dropna(subset=["vessel_code", "_arr"]).sort_values("_arr")

    # Recalada previa del mismo barco: cota inferior del viaje (NaT si es la 1ª).
    refs["_prev_arr"] = refs.groupby("vessel_code")["_arr"].shift()

    izq = df.reset_index().sort_values("_dt")  # 'index' preserva el orden original
    matched = pd.merge_asof(
        izq, refs[["zarpe_id", "vessel_code", "_arr", "_prev_arr"]],
        left_on="_dt", right_on="_arr", by="vessel_code", direction="forward",
    )
    tope = pd.Timedelta(days=MAX_TRIP_DAYS)
    dentro = (
        (matched["_arr"] - matched["_dt"] <= tope)
        & (matched["_prev_arr"].isna() | (matched["_dt"] > matched["_prev_arr"]))
    )
    matched.loc[~dentro, "zarpe_id"] = pd.NA

    out = df.copy()
    out["zarpe_id"] = matched.set_index("index")["zarpe_id"].reindex(out.index)
    out["zarpe_id"] = pd.to_numeric(out["zarpe_id"], errors="coerce").astype("Int64")
    return out


def identificar(df: pd.DataFrame, refs: pd.DataFrame,
                ports: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Etiqueta los pings con zarpe_id (de referencia) y arma el resumen por zarpe."""
    df = df.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["speed_kt"] = pd.to_numeric(df["speed_kt"], errors="coerce")
    df["_dt"] = pd.to_datetime(df["location_datetime"], errors="coerce")
    df["vessel_code"] = df["vessel_code"].fillna("").astype(str).str.strip()

    n_in = len(df)
    df = df.dropna(subset=["latitude", "longitude", "_dt"])
    df = df[df["vessel_code"] != ""]
    n_sin_datos = n_in - len(df)

    # Asignar el zarpe de referencia y descartar los pings sin zarpe.
    df = _asignar_zarpe(df, refs)
    n_emparejables = len(df)
    df = df[df["zarpe_id"].notna()].copy()
    n_sin_zarpe = n_emparejables - len(df)

    # Ordenar por zarpe (cronológico dentro del viaje) para los cálculos de tramo.
    df = df.sort_values(["zarpe_id", "_dt"], kind="stable").reset_index(drop=True)

    # Distancia al puerto más cercano (solo contexto).
    df["dist_port_km"], df["nearest_port"] = _dist_a_puertos(
        df["latitude"], df["longitude"], ports
    )

    # Tramo en km entre pings consecutivos del mismo zarpe (distancia recorrida).
    step_km = _haversine(
        df["latitude"].shift(), df["longitude"].shift(),
        df["latitude"], df["longitude"],
    )
    same_trip = df["zarpe_id"].eq(df["zarpe_id"].shift()).fillna(False)
    df["_step_km"] = np.where(same_trip, step_km, 0.0)

    grp = df.groupby("zarpe_id", sort=True)
    resumen = grp.agg(
        rpa=("rpa", "first"),
        vessel_code=("vessel_code", "first"),
        vessel_name=("vessel_name", "first"),
        start_datetime=("_dt", "min"),
        end_datetime=("_dt", "max"),
        n_pings=("_dt", "size"),
        max_dist_km=("dist_port_km", "max"),
        track_km=("_step_km", "sum"),
        mean_speed_kt=("speed_kt", "mean"),
        max_speed_kt=("speed_kt", "max"),
        centroid_lat=("latitude", "mean"),
        centroid_lon=("longitude", "mean"),
        start_port=("nearest_port", "first"),
        start_dist_km=("dist_port_km", "first"),
        end_port=("nearest_port", "last"),
        end_dist_km=("dist_port_km", "last"),
    ).reset_index()

    resumen["duration_h"] = (
        (resumen["end_datetime"] - resumen["start_datetime"]).dt.total_seconds() / 3600.0
    )

    # Redondeos de presentación.
    df["dist_port_km"] = df["dist_port_km"].round(3)
    for col, nd in [("max_dist_km", 3), ("track_km", 3),
                    ("mean_speed_kt", 2), ("max_speed_kt", 2),
                    ("centroid_lat", 5), ("centroid_lon", 5),
                    ("start_dist_km", 3), ("end_dist_km", 3), ("duration_h", 2)]:
        resumen[col] = resumen[col].round(nd)
    for col in ["start_datetime", "end_datetime"]:
        resumen[col] = resumen[col].dt.strftime("%Y-%m-%d %H:%M:%S")

    pings_cols = [
        "zarpe_id", "rpa", "vessel_code", "vessel_name", "radio_call_sign",
        "location_datetime", "latitude", "longitude", "heading", "speed_kt",
        "dist_port_km", "nearest_port",
    ]
    resumen_cols = [
        "zarpe_id", "rpa", "vessel_code", "vessel_name", "start_datetime",
        "end_datetime", "duration_h", "n_pings", "max_dist_km", "track_km",
        "mean_speed_kt", "max_speed_kt", "centroid_lat", "centroid_lon",
        "start_port", "start_dist_km", "end_port", "end_dist_km",
    ]

    stats = {
        "sin_datos": n_sin_datos,
        "sin_zarpe": n_sin_zarpe,
        "pings_en_zarpe": len(df),
        "zarpes_validos": len(resumen),
    }
    return df[pings_cols], resumen[resumen_cols], stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    input_csv = FILTERED_DIR / f"locations_{FLEET_NAME}_{tag}_registry.csv"
    pings_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{tag}_zarpes.csv"
    summary_csv = OUTPUT_DIR / f"zarpes_{FLEET_NAME}_{tag}_summary.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no existe {input_csv}.\n"
            "       Generá las posiciones filtradas primero con:\n"
            "           uv run python -m processing.locations.filter.filter_registry",
            file=sys.stderr,
        )
        sys.exit(1)

    if not UNIFIED_ZARPES_CSV.exists():
        print(
            f"ERROR: no existe {UNIFIED_ZARPES_CSV}.\n"
            "       Generá el dataset unificado de zarpes con captura primero con:\n"
            "           uv run python -m processing.capture.unify.unify_zarpes",
            file=sys.stderr,
        )
        sys.exit(1)

    ports = active_region().port_coords()
    df = pd.read_csv(input_csv, dtype=str)
    refs = pd.read_csv(UNIFIED_ZARPES_CSV, dtype=str)

    pings, resumen, stats = identificar(df, refs, ports)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pings.to_csv(pings_csv, index=False)
    resumen.to_csv(summary_csv, index=False)

    dur = pd.to_numeric(resumen["duration_h"], errors="coerce")
    print(
        f"Identificando zarpes (ventana hacia la recalada, tope {MAX_TRIP_DAYS}d: {UNIFIED_ZARPES_CSV.name})\n"
        f"  Entrada: {input_csv}\n"
        f"  Puertos (contexto): {', '.join(p['nombre'] for p in ports)}\n\n"
        f"Pings de entrada:                {len(df):,}\n"
        f"  sin fecha/coords/vessel_code:  {stats['sin_datos']:,}\n"
        f"  sin zarpe de referencia:       {stats['sin_zarpe']:,}\n"
        f"  asignados a un zarpe:          {stats['pings_en_zarpe']:,}\n"
        f"Zarpes de referencia cubiertos:  {stats['zarpes_validos']:,}\n"
        f"Duración (h) — mediana / p90:    {dur.median():.1f} / {dur.quantile(0.9):.1f}\n"
        f"Archivos escritos:\n"
        f"  {pings_csv}\n"
        f"  {summary_csv}"
    )


if __name__ == "__main__":
    main()
