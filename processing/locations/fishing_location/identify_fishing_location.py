"""
Identifica, para cada zarpe de un solo lance (`filter_single_haul.py`), el LUGAR
donde ocurrió la pesca: el punto en que la embarcación de cerco caló la red.

El arte es cerco (purse seine): un lance es una maniobra LENTA y CIRCULAR mar
adentro (el barco rodea el cardumen). Ese comportamiento se ve en la traza VMS
en dos señales: la VELOCIDAD baja muy por debajo de la de tránsito (~5-7 kt) y el
RUMBO gira con fuerza. Esta etapa clasifica el comportamiento de cada ping con
ambas señales y emite una única ubicación de lance por zarpe.

Algoritmo:
  1. Tasa de giro por ping: |Δrumbo| entre pings consecutivos del mismo zarpe
     (con corrección de salto 0/360).
  2. Pings candidatos: mar adentro (dist_port_km >= OFFSHORE_MIN_KM) y velocidad
     en la ventana de pesca [FISHING_SPEED_MIN_KT, FISHING_SPEED_MAX_KT]. La
     velocidad filtra los candidatos; el giro se exige a nivel de bout para no
     descartar un ping recto suelto dentro de un cerco circular.
  3. Bouts: los candidatos de cada zarpe se parten en tramos contiguos donde el
     hueco temporal supera GAP_SPLIT_MIN (a cadencia ~8 min, >20 min = corte).
  4. Bout dominante: de los bouts con >= MIN_BOUT_PINGS pings y giro medio
     >= TURN_MIN_DEG (aquí entra el rumbo: descarta la deriva recta nocturna) se
     elige el de mayor giro acumulado (el cerco circular acumula más cambio de
     rumbo), con desempate por nº de pings y luego por inicio más temprano.
  5. Ubicación del lance: el centroide (lat/lon medio) de los pings del bout
     elegido; se anota su distancia al puerto más cercano como contexto.

Los zarpes sin ningún bout válido se conservan con haul_status == "sin_pesca" y
ubicación nula, para que aguas abajo se vean todos los zarpes de un lance.

Entrada:
  data/processing/locations/single_haul/locations_flota_artesanal_<rango>_single_haul.csv
  data/processing/locations/single_haul/zarpes_flota_artesanal_<rango>_single_haul_summary.csv
  coordenadas de puerto de la región activa (processing/utils/regions.py)

Esta es la ÚLTIMA etapa del pipeline de localizaciones; su resumen por zarpe es
el producto final y se escribe en `data/output/` (junto al producto del pipeline
de captura). La traza de pings etiquetada queda como artefacto auditable en la
carpeta de la etapa.

Salidas:
  data/processing/locations/fishing_location/locations_flota_artesanal_<rango>_fishing.csv
      → (intermedio auditable) los pings + turn_deg, behavior (transito/candidato/pesca), is_haul
  data/output/zarpes_atacama_haul_location.csv
      → (PRODUCTO FINAL) una fila por zarpe con la ubicación del lance (haul_lat/haul_lon, ventana, etc.)

Uso:
    uv run python -m processing.locations.fishing_location.identify_fishing_location
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME
from processing.utils.regions import active_region


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
SINGLE_HAUL_DIR = DATA_DIR / "single_haul"
OUTPUT_DIR = DATA_DIR / "fishing_location"            # intermedio (traza de pings)
FINAL_OUTPUT_DIR = DATA_DIR.parent.parent / "output"  # producto final (resumen por zarpe)
UNIFIED_ZARPES_CSV = FINAL_OUTPUT_DIR / "zarpes_atacama_capture.csv"

EARTH_RADIUS_KM = 6371.0

# --- Umbrales de detección de pesca (palancas de sensibilidad) -------------
# Guarda: descarta la maniobra cerca de puerto (poco sensible; los pings lentos
# observados ya están a >= 6.6 km).
OFFSHORE_MIN_KM = 8.0
# Excluye pings totalmente detenidos / ruido.
FISHING_SPEED_MIN_KT = 0.3
# Por debajo de la velocidad de tránsito (~5-7 kt) — palanca principal.
FISHING_SPEED_MAX_KT = 4.0
# Giro medio mínimo que confirma maniobra circular vs deriva recta — palanca.
TURN_MIN_DEG = 20.0
# Hueco temporal (min) que separa bouts (>~2 reportes perdidos a cadencia 8 min).
GAP_SPLIT_MIN = 20.0
# Un bout necesita al menos esta cantidad de pings.
MIN_BOUT_PINGS = 2


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


def _dist_min_puerto(lat: float, lon: float, ports: list[dict]) -> tuple[float, str]:
    """Distancia (km) y nombre del puerto más cercano a un punto escalar."""
    dists = [(_haversine(lat, lon, p["latitud"], p["longitud"]), p["nombre"]) for p in ports]
    return min(dists, key=lambda t: t[0])


def _turning_rate(df: pd.DataFrame) -> pd.Series:
    """|Δrumbo| (grados) entre pings consecutivos del mismo zarpe.

    Corrige el salto 0/360 con ((Δ + 180) % 360) - 180. El primer ping de cada
    zarpe no tiene anterior → 0.
    """
    prev = df.groupby("zarpe_id")["heading"].shift()
    delta = ((df["heading"] - prev + 180) % 360) - 180
    return delta.abs().fillna(0.0)


def _clasificar(df: pd.DataFrame) -> pd.Series:
    """Marca los pings candidatos a pesca: mar adentro y en la ventana de velocidad."""
    return (
        (df["dist_port_km"] >= OFFSHORE_MIN_KM)
        & (df["speed_kt"] >= FISHING_SPEED_MIN_KT)
        & (df["speed_kt"] <= FISHING_SPEED_MAX_KT)
    )


def _segmentar_bouts(sub: pd.DataFrame) -> pd.Series:
    """Id de bout para los candidatos de un zarpe (corta donde el hueco > GAP_SPLIT_MIN)."""
    gap_min = sub["_dt"].diff().dt.total_seconds() / 60.0
    return (gap_min > GAP_SPLIT_MIN).fillna(False).cumsum()


def _seleccionar_bout(sub: pd.DataFrame) -> pd.Index | None:
    """Índice (en `sub`) de los pings del bout dominante, o None si no hay ninguno válido.

    `sub` son los pings candidatos de UN zarpe, ya ordenados por tiempo. Conserva
    los bouts con >= MIN_BOUT_PINGS y giro medio >= TURN_MIN_DEG; elige el de mayor
    giro acumulado, desempate por nº de pings y luego inicio más temprano.
    """
    if sub.empty:
        return None
    bout = _segmentar_bouts(sub)
    mejor = None  # (cum_turn, n_pings, -inicio_ordinal, indices)
    for _, grp in sub.groupby(bout):
        if len(grp) < MIN_BOUT_PINGS or grp["turn_deg"].mean() < TURN_MIN_DEG:
            continue
        clave = (grp["turn_deg"].sum(), len(grp), -grp["_dt"].iloc[0].value)
        if mejor is None or clave > mejor[0]:
            mejor = (clave, grp.index)
    return None if mejor is None else mejor[1]


def identificar_pesca(df: pd.DataFrame, ports: list[dict],
                      captura: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Etiqueta el comportamiento de cada ping y arma el resumen con la ubicación del lance.

    `captura` es el dataset unificado de zarpes con captura; aporta `jack_mackerel_kg`
    por `zarpe_id` (la captura de jurel del zarpe), que se anexa al resumen.
    """
    captura = captura[["zarpe_id", "jack_mackerel_kg"]].copy()
    captura["zarpe_id"] = pd.to_numeric(captura["zarpe_id"], errors="coerce").astype("Int64")
    captura["jack_mackerel_kg"] = pd.to_numeric(captura["jack_mackerel_kg"], errors="coerce")
    kg_por_zarpe = captura.dropna(subset=["zarpe_id"]).set_index("zarpe_id")["jack_mackerel_kg"]

    df = df.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["speed_kt"] = pd.to_numeric(df["speed_kt"], errors="coerce")
    df["heading"] = pd.to_numeric(df["heading"], errors="coerce")
    df["dist_port_km"] = pd.to_numeric(df["dist_port_km"], errors="coerce")
    df["zarpe_id"] = pd.to_numeric(df["zarpe_id"], errors="coerce").astype("Int64")
    df["_dt"] = pd.to_datetime(df["location_datetime"], errors="coerce")

    df = df.sort_values(["zarpe_id", "_dt"], kind="stable").reset_index(drop=True)

    # Señales por ping.
    df["turn_deg"] = _turning_rate(df)
    df["_cand"] = _clasificar(df)

    # Selección del bout dominante por zarpe.
    df["behavior"] = "transito"
    df.loc[df["_cand"], "behavior"] = "candidato"
    df["is_haul"] = 0

    filas_resumen = []
    n_con_lance = 0
    for zid, sub in df.groupby("zarpe_id", sort=True):
        meta = sub.iloc[0]
        kg = kg_por_zarpe.get(zid, pd.NA)
        cand = sub[sub["_cand"]]
        idx = _seleccionar_bout(cand)

        if idx is None:
            filas_resumen.append({
                "zarpe_id": zid, "rpa": meta["rpa"], "vessel_code": meta["vessel_code"],
                "vessel_name": meta["vessel_name"], "jack_mackerel_kg": kg,
                "haul_lat": pd.NA, "haul_lon": pd.NA, "haul_start": pd.NA, "haul_end": pd.NA,
                "haul_duration_h": pd.NA, "haul_n_pings": 0, "haul_mean_speed_kt": pd.NA,
                "haul_cum_turn_deg": pd.NA, "haul_dist_port_km": pd.NA, "nearest_port": pd.NA,
            })
            continue

        n_con_lance += 1
        df.loc[idx, "behavior"] = "pesca"
        df.loc[idx, "is_haul"] = 1
        lance = df.loc[idx]
        lat, lon = lance["latitude"].mean(), lance["longitude"].mean()
        dist_km, puerto = _dist_min_puerto(lat, lon, ports)
        filas_resumen.append({
            "zarpe_id": zid, "rpa": meta["rpa"], "vessel_code": meta["vessel_code"],
            "vessel_name": meta["vessel_name"], "jack_mackerel_kg": kg,
            "haul_lat": round(lat, 5), "haul_lon": round(lon, 5),
            "haul_start": lance["_dt"].min(), "haul_end": lance["_dt"].max(),
            "haul_duration_h": round(
                (lance["_dt"].max() - lance["_dt"].min()).total_seconds() / 3600.0, 2),
            "haul_n_pings": int(len(lance)),
            "haul_mean_speed_kt": round(lance["speed_kt"].mean(), 2),
            "haul_cum_turn_deg": round(lance["turn_deg"].sum(), 3),
            "haul_dist_port_km": round(dist_km, 3), "nearest_port": puerto,
        })

    resumen = pd.DataFrame(filas_resumen)
    for col in ["haul_start", "haul_end"]:
        resumen[col] = pd.to_datetime(resumen[col]).dt.strftime("%Y-%m-%d %H:%M:%S")

    df["turn_deg"] = df["turn_deg"].round(1)

    pings_cols = [
        "zarpe_id", "rpa", "vessel_code", "vessel_name", "radio_call_sign",
        "location_datetime", "latitude", "longitude", "heading", "speed_kt",
        "dist_port_km", "nearest_port", "turn_deg", "behavior", "is_haul",
    ]
    resumen_cols = [
        "zarpe_id", "vessel_code", "vessel_name", "jack_mackerel_kg",
        "haul_lat", "haul_lon", "haul_start", "haul_end", "haul_duration_h",
        "haul_n_pings", "haul_mean_speed_kt", "haul_dist_port_km", "nearest_port",
    ]

    stats = {
        "zarpes": int(resumen["zarpe_id"].nunique()),
        "con_pesca": n_con_lance,
        "sin_pesca": int(resumen["zarpe_id"].nunique()) - n_con_lance,
        "pings_pesca": int((df["behavior"] == "pesca").sum()),
    }
    return df[pings_cols], resumen[resumen_cols], stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    input_csv = SINGLE_HAUL_DIR / f"locations_{FLEET_NAME}_{tag}_single_haul.csv"
    pings_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{tag}_fishing.csv"
    summary_csv = FINAL_OUTPUT_DIR / "zarpes_atacama_haul_location.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no existe {input_csv}.\n"
            "       Generá los zarpes de un solo lance primero con:\n"
            "           uv run python -m processing.locations.single_haul.filter_single_haul",
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
    captura = pd.read_csv(UNIFIED_ZARPES_CSV, dtype=str)

    pings, resumen, stats = identificar_pesca(df, ports, captura)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pings.to_csv(pings_csv, index=False)
    resumen.to_csv(summary_csv, index=False)

    dist = pd.to_numeric(resumen["haul_dist_port_km"], errors="coerce").dropna()
    dist_line = (
        f"Distancia del lance a puerto (km) — mediana: {dist.median():.1f}"
        if not dist.empty else "Distancia del lance a puerto: sin lances"
    )
    print(
        f"Identificando la ubicación del lance (velocidad + rumbo, arte cerco)\n"
        f"  Entrada: {input_csv}\n"
        f"  Ventana de pesca: {FISHING_SPEED_MIN_KT}-{FISHING_SPEED_MAX_KT} kt, "
        f"giro medio >= {TURN_MIN_DEG} grados, mar adentro >= {OFFSHORE_MIN_KM} km\n\n"
        f"Zarpes de entrada:            {stats['zarpes']:,}\n"
        f"  con lance identificado:     {stats['con_pesca']:,}\n"
        f"  sin pesca detectable:       {stats['sin_pesca']:,}\n"
        f"Pings etiquetados como pesca: {stats['pings_pesca']:,}\n"
        f"{dist_line}\n"
        f"Archivos escritos:\n"
        f"  (intermedio) {pings_csv}\n"
        f"  (producto final) {summary_csv}"
    )


if __name__ == "__main__":
    main()
