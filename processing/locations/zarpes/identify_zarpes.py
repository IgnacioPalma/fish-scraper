"""
Agrupa las posiciones VMS de la flota del registro (`filter_registry.py`) en
"zarpes" (viajes de pesca), para poder analizar la actividad a nivel de viaje
en vez de ping a ping.

Definición de zarpe (criterio "hueco de reporte"):
  La cadencia normal del VMS mar adentro es de ~8-15 min entre pings. Cuando la
  embarcación recala, el transpondedor deja de reportar mientras está en puerto
  (en estos datos los pings casi nunca llegan al muelle: el más cercano queda a
  ~1 km y solo ~480 de 165 000 caen a <= 5 km a baja velocidad). Por eso el
  corte de viaje NO se puede detectar por cercanía a puerto, sino por el SILENCIO
  de reporte: un hueco > GAP_HOURS entre pings marca una estadía en puerto.

  Un zarpe es la corrida de pings consecutivos de una misma embarcación cuyos
  saltos temporales son <= GAP_HOURS. Un hueco mayor (o el cambio de barco)
  abre un zarpe nuevo. A cada zarpe se le anota, como contexto, el puerto más
  cercano a su primer y último ping (puerto de zarpe / de recalada aproximados).

Se descartan como ruido los zarpes con menos de MIN_TRIP_PINGS pings; los
válidos se renumeran 1..N por orden cronológico.

Entrada:
  data/processing/locations/filtered/locations_flota_artesanal_<rango>_registry.csv
  processing/bitacora/puertos_atacama.json   (coordenadas de puertos)

Salidas:
  data/processing/locations/zarpes/locations_flota_artesanal_<rango>_zarpes.csv
      → los pings de entrada + dist_port_km, nearest_port, zarpe_id
  data/processing/locations/zarpes/zarpes_flota_artesanal_<rango>_summary.csv
      → una fila por zarpe (inicio/fin, duración, nº pings, distancia máx. a
        puerto, distancia recorrida, puerto de zarpe/recalada aproximados, etc.)

Uso:
    uv run python -m processing.locations.zarpes.identify_zarpes
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
FILTERED_DIR = DATA_DIR / "filtered"
OUTPUT_DIR = DATA_DIR / "zarpes"
PORTS_JSON = Path(__file__).resolve().parents[2] / "bitacora" / "puertos_atacama.json"

# Umbrales del criterio de zarpe (constantes ajustables).
GAP_HOURS = 6.0        # silencio de reporte que separa dos viajes (estadía en puerto)
MIN_TRIP_PINGS = 2     # zarpes con menos pings se descartan como ruido

EARTH_RADIUS_KM = 6371.0


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


def identificar(df: pd.DataFrame, ports: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Etiqueta los pings con zarpe_id y construye la tabla resumen por zarpe."""
    df = df.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["speed_kt"] = pd.to_numeric(df["speed_kt"], errors="coerce")
    df["_dt"] = pd.to_datetime(df["location_datetime"], errors="coerce")

    n_in = len(df)
    df = df.dropna(subset=["latitude", "longitude", "_dt"])
    n_sin_tiempo = n_in - len(df)

    df = df.sort_values(["rpa", "_dt"], kind="stable").reset_index(drop=True)

    # Distancia al puerto más cercano (solo contexto, no define el viaje).
    df["dist_port_km"], df["nearest_port"] = _dist_a_puertos(
        df["latitude"], df["longitude"], ports
    )

    # Corte de viaje: hueco de reporte > GAP_HOURS o cambio de barco (gap NaN).
    gap_h = df.groupby("rpa")["_dt"].diff().dt.total_seconds() / 3600.0
    df["_gap_before_h"] = gap_h
    new_trip = gap_h.isna() | (gap_h > GAP_HOURS)
    df["_trip_key"] = new_trip.cumsum()

    # Tramo en km entre pings consecutivos del mismo viaje (distancia recorrida).
    step_km = _haversine(
        df["latitude"].shift(), df["longitude"].shift(),
        df["latitude"], df["longitude"],
    )
    same_trip = df["_trip_key"].eq(df["_trip_key"].shift())
    df["_step_km"] = np.where(same_trip, step_km, 0.0)

    grp = df.groupby("_trip_key", sort=False)
    resumen = grp.agg(
        rpa=("rpa", "first"),
        vessel_name=("vessel_name", "first"),
        start_datetime=("_dt", "min"),
        end_datetime=("_dt", "max"),
        n_pings=("_dt", "size"),
        # iloc[0], no "first": el primer viaje de cada barco tiene gap NaN y
        # "first" lo saltaría devolviendo la cadencia del 2º ping (~8 min).
        gap_before_h=("_gap_before_h", lambda s: s.iloc[0]),
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

    # Descartar ruido (zarpes de un solo ping) y renumerar 1..N cronológicamente.
    n_total = len(resumen)
    valido = resumen["n_pings"] >= MIN_TRIP_PINGS
    n_descartados = int((~valido).sum())
    resumen = resumen[valido].sort_values(["rpa", "start_datetime"]).reset_index(drop=True)
    resumen.insert(0, "zarpe_id", np.arange(1, len(resumen) + 1))

    key_to_id = dict(zip(resumen["_trip_key"], resumen["zarpe_id"]))
    df["zarpe_id"] = df["_trip_key"].map(key_to_id).astype("Int64")

    # Redondeos de presentación.
    df["dist_port_km"] = df["dist_port_km"].round(3)
    for col, nd in [("gap_before_h", 2), ("max_dist_km", 3), ("track_km", 3),
                    ("mean_speed_kt", 2), ("max_speed_kt", 2),
                    ("centroid_lat", 5), ("centroid_lon", 5),
                    ("start_dist_km", 3), ("end_dist_km", 3), ("duration_h", 2)]:
        resumen[col] = resumen[col].round(nd)
    for col in ["start_datetime", "end_datetime"]:
        resumen[col] = resumen[col].dt.strftime("%Y-%m-%d %H:%M:%S")

    pings_cols = [
        "zarpe_id", "rpa", "vessel_name", "radio_call_sign", "location_datetime",
        "latitude", "longitude", "heading", "speed_kt", "dist_port_km", "nearest_port",
    ]
    resumen_cols = [
        "zarpe_id", "rpa", "vessel_name", "start_datetime", "end_datetime",
        "duration_h", "gap_before_h", "n_pings", "max_dist_km", "track_km",
        "mean_speed_kt", "max_speed_kt", "centroid_lat", "centroid_lon",
        "start_port", "start_dist_km", "end_port", "end_dist_km",
    ]

    stats = {
        "sin_tiempo": n_sin_tiempo,
        "zarpes_provisionales": n_total,
        "zarpes_descartados": n_descartados,
        "zarpes_validos": len(resumen),
        "pings_en_zarpe": int(df["zarpe_id"].notna().sum()),
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

    ports = json.loads(PORTS_JSON.read_text(encoding="utf-8"))
    df = pd.read_csv(input_csv, dtype=str)

    pings, resumen, stats = identificar(df, ports)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pings.to_csv(pings_csv, index=False)
    resumen.to_csv(summary_csv, index=False)

    dur = pd.to_numeric(resumen["duration_h"], errors="coerce")
    print(
        f"Identificando zarpes (corte por hueco de reporte > {GAP_HOURS} h)\n"
        f"  Entrada: {input_csv}\n"
        f"  Puertos (contexto): {', '.join(p['nombre'] for p in ports)}\n\n"
        f"Pings de entrada:                {len(df):,}\n"
        f"  sin fecha/coords (descartados):{stats['sin_tiempo']:,}\n"
        f"  asignados a un zarpe:          {stats['pings_en_zarpe']:,}\n"
        f"Zarpes detectados:               {stats['zarpes_provisionales']:,}\n"
        f"  descartados (1 ping):          {stats['zarpes_descartados']:,}\n"
        f"  válidos:                       {stats['zarpes_validos']:,}\n"
        f"Duración (h) — mediana / p90:    {dur.median():.1f} / {dur.quantile(0.9):.1f}\n"
        f"Archivos escritos:\n"
        f"  {pings_csv}\n"
        f"  {summary_csv}"
    )


if __name__ == "__main__":
    main()
