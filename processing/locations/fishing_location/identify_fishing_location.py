"""
Identifica, para cada zarpe (`identify_zarpes.py`), el LUGAR donde ocurrió la
pesca: el punto en que la embarcación de cerco caló la red.

El arte es cerco (purse seine): un lance es una maniobra LENTA y CIRCULAR mar
adentro (el barco rodea el cardumen). Ese comportamiento se ve en la traza VMS
en dos señales: la VELOCIDAD baja muy por debajo de la de tránsito (~5-7 kt) y el
RUMBO gira con fuerza. Esta etapa clasifica el comportamiento de cada ping con
ambas señales y emite una única ubicación de lance por zarpe.

Algoritmo:
  1. Giro por ping: Δrumbo CON SIGNO entre pings consecutivos del mismo zarpe
     (con corrección de salto 0/360). El valor absoluto colorea el ping; la suma
     CON SIGNO sobre un bout (giro neto) mide el "anillo" del cerco.
  2. Pings candidatos: mar adentro (dist_port_km >= OFFSHORE_MIN_KM) y velocidad
     en la ventana de pesca [FISHING_SPEED_MIN_KT, FISHING_SPEED_MAX_KT]. La
     velocidad filtra los candidatos; la geometría circular se exige a nivel de
     bout para no descartar un ping recto suelto dentro de un cerco circular.
  3. Bouts: los candidatos de cada zarpe se parten en tramos contiguos donde el
     hueco temporal supera GAP_SPLIT_MIN (a cadencia ~8 min, >20 min = corte).
  4. Bouts de pesca: dos señales propias del cerco, ROBUSTAS A LA CADENCIA (no
     dependen de promediar |Δrumbo| por ping, que crece con el hueco temporal):
       - giro NETO |Σ Δrumbo| >= NET_TURN_MIN_DEG (un lance cierra ~±360°), o
       - compacidad = largo_de_traza / diagonal_bbox >= COMPACT_MIN
         (un círculo ≈ 2.2, una recta ≈ 1: separa el cerco de la deriva recta).
     Califica como lance todo bout con >= MIN_BOUT_PINGS pings que cumple
     cualquiera de las dos. Un zarpe puede tener VARIOS lances; se cuentan todos
     (`n_hauls`) y se marcan en la traza con `haul_index`.
  5. Ubicación del lance: se elige el bout más "anillo" (mayor giro neto, luego
     compacidad, luego nº de pings) como lance representativo del zarpe y se
     reporta el centroide (lat/lon medio) de sus pings + su distancia a puerto.
     Mantener una fila por zarpe preserva el cruce 1:1 con la captura del viaje
     (la captura es del zarpe, no del lance individual).

Los zarpes sin ningún bout de pesca se conservan con ubicación nula (`n_hauls` 0),
para que aguas abajo se vean todos los zarpes.

Entrada:
  data/processing/locations/zarpes/locations_flota_artesanal_<rango>_zarpes.csv
  coordenadas de puerto de la región activa (processing/utils/regions.py)

Esta es la penúltima etapa del pipeline de localizaciones; su resumen por zarpe y
la traza de pings etiquetada quedan en la carpeta de la etapa
(`data/processing/locations/fishing_location/`). La etapa `single_haul` recorta
ese resumen al conjunto de modelado.

Salidas:
  data/processing/locations/fishing_location/locations_flota_artesanal_<rango>_fishing.csv
      → (intermedio auditable) los pings + turn_deg, behavior (transito/candidato/pesca), is_haul
  data/processing/locations/fishing_location/zarpes_atacama_haul_location.csv
      → (PRODUCTO) una fila por zarpe con la ubicación del lance (haul_lat/haul_lon, ventana, etc.)

Uso:
    uv run python -m processing.locations.fishing_location.identify_fishing_location
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from processing.utils.datasets import active_source
from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME
from processing.utils.regions import active_region


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"

EARTH_RADIUS_KM = 6371.0

# --- Umbrales de detección de pesca (palancas de sensibilidad) -------------
# Guarda: descarta la maniobra cerca de puerto (poco sensible; los pings lentos
# observados ya están a >= 6.6 km).
OFFSHORE_MIN_KM = 8.0
# Excluye pings totalmente detenidos / ruido.
FISHING_SPEED_MIN_KT = 0.3
# Por debajo de la velocidad de tránsito (~5-7 kt) — palanca principal.
FISHING_SPEED_MAX_KT = 4.0
# Giro NETO (|Σ Δrumbo|, con signo) que evidencia el anillo del cerco. Un lance
# cierra ~±360°; 160° tolera anillos parciales / ruido sin admitir deriva recta.
# Robusto a la cadencia (no promedia |Δrumbo| por ping). — palanca.
NET_TURN_MIN_DEG = 160.0
# Compacidad = largo_de_traza / diagonal_bbox del bout. Círculo ≈ 2.2, recta ≈ 1.
# Captura el lance circular aun cuando el giro neto se cancela (ochos / dobles
# pasadas). — palanca.
COMPACT_MIN = 1.6
# Piso de compacidad para aceptar un lance por giro neto: descarta el zigzag recto
# (compacidad < 1) cuyo |Σ Δrumbo| sube por glitches de rumbo en pocos pings, sin
# trazar un anillo. Un anillo real tiene la traza más larga que su bbox.
COMPACT_FLOOR = 1.2
# Hueco temporal (min) que separa bouts (>~2 reportes perdidos a cadencia 8 min).
GAP_SPLIT_MIN = 20.0
# Un bout necesita al menos esta cantidad de pings (≥~16-24 min de circuleo lento
# a cadencia 8 min; un anillo necesita varios puntos para medir giro/compacidad).
MIN_BOUT_PINGS = 3


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


def _turn_delta(df: pd.DataFrame) -> pd.Series:
    """Δrumbo CON SIGNO (grados) entre pings consecutivos del mismo zarpe.

    Corrige el salto 0/360 con ((Δ + 180) % 360) - 180 (rango [-180, 180]; signo
    = sentido del giro). El primer ping de cada zarpe no tiene anterior → 0. El
    valor absoluto colorea el ping; la suma con signo sobre un bout da el giro
    neto (el "anillo" del cerco).
    """
    prev = df.groupby("zarpe_id")["heading"].shift()
    delta = ((df["heading"] - prev + 180) % 360) - 180
    return delta.fillna(0.0)


def _bout_metrics(grp: pd.DataFrame) -> dict:
    """Métricas geométricas de un bout (pings candidatos contiguos, ordenados).

    - net_turn: |Σ Δrumbo con signo| — cuánto "cierra" el anillo (~360° = lance).
    - cum_turn: Σ |Δrumbo| — giro total acumulado (desempate).
    - path_km:  largo de la traza (suma de tramos haversine consecutivos).
    - span_km:  diagonal del bbox del bout (≈ diámetro de la maniobra).
    - compactness: path_km / span_km — círculo ≈ 2.2, recta ≈ 1.
    """
    lat = grp["latitude"].to_numpy(dtype=float)
    lon = grp["longitude"].to_numpy(dtype=float)
    head = grp["heading"].to_numpy(dtype=float)
    path_km = float(_haversine(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum()) if len(lat) > 1 else 0.0
    span_km = float(_haversine(lat.min(), lon.min(), lat.max(), lon.max()))
    # Giro DENTRO del bout: el primer ping no arrastra el viraje del tránsito que
    # lo precede (esa contaminación de borde inflaba el giro neto de bouts cortos).
    dhead = ((np.diff(head) + 180) % 360) - 180 if len(head) > 1 else np.array([])
    return {
        "net_turn": float(abs(dhead.sum())),
        "cum_turn": float(np.abs(dhead).sum()),
        "path_km": path_km,
        "span_km": span_km,
        "compactness": path_km / max(span_km, 0.05),
    }


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


def _es_lance(m: dict) -> bool:
    """¿El bout exhibe la geometría circular del cerco?

    Un anillo nítido (compacidad >= COMPACT_MIN) califica por sí solo. Un anillo
    parcial (giro neto alto) califica solo si además es algo compacto
    (>= COMPACT_FLOOR), lo que descarta el zigzag recto con giro neto inflado.
    """
    return m["compactness"] >= COMPACT_MIN or (
        m["net_turn"] >= NET_TURN_MIN_DEG and m["compactness"] >= COMPACT_FLOOR
    )


def _bouts_candidatos(sub: pd.DataFrame) -> list[tuple[pd.Index, dict]]:
    """Bouts candidatos de UN zarpe, ordenados de más a menos "anillo".

    `sub` son los pings candidatos de un zarpe (mar adentro + velocidad de pesca),
    ya ordenados por tiempo. Se parten en bouts por hueco temporal y se conserva
    todo bout con >= MIN_BOUT_PINGS pings. NO se descarta por geometría: el filtro
    circular se aplica después como CONFIANZA (`is_set`), para no perder recall en
    zarpes con captura cuya traza VMS no cierra un anillo nítido a cadencia gruesa.

    El orden prioriza el bout más "anillo": primero los que son lance circular
    (`_es_lance`), luego por giro neto, compacidad, nº de pings e inicio. El primero
    es el lance representativo del zarpe; los `is_set` son los lances confiables.
    """
    if sub.empty:
        return []
    bout = _segmentar_bouts(sub)
    bouts = []
    for _, grp in sub.groupby(bout):
        if len(grp) < MIN_BOUT_PINGS:
            continue
        m = _bout_metrics(grp)
        m["is_set"] = _es_lance(m)
        # Prioriza la geometría de anillo (compacidad) sobre el giro neto crudo,
        # que es ruidoso con pocos pings; desempata por giro neto, nº pings, inicio.
        clave = (m["is_set"], m["compactness"], m["net_turn"], len(grp), -grp["_dt"].iloc[0].value)
        bouts.append((clave, grp.index, m))
    bouts.sort(key=lambda t: t[0], reverse=True)
    return [(idx, m) for _, idx, m in bouts]


def identificar_pesca(df: pd.DataFrame, ports: list[dict],
                      captura: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Etiqueta el comportamiento de cada ping y arma el resumen con la ubicación del lance.

    `captura` es el dataset unificado de zarpes con captura; aporta `jack_mackerel_tons`
    por `zarpe_id` (la captura de jurel del zarpe), que se anexa al resumen.
    """
    captura = captura[["zarpe_id", "jack_mackerel_tons", "principal_catch"]].copy()
    captura["zarpe_id"] = pd.to_numeric(captura["zarpe_id"], errors="coerce").astype("Int64")
    captura["jack_mackerel_tons"] = pd.to_numeric(captura["jack_mackerel_tons"], errors="coerce")
    captura["principal_catch"] = (
        captura["principal_catch"].astype(str).str.strip().str.lower()
        .map({"true": True, "false": False})
    )
    cap = captura.dropna(subset=["zarpe_id"]).set_index("zarpe_id")
    tons_por_zarpe = cap["jack_mackerel_tons"]
    principal_por_zarpe = cap["principal_catch"]

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
    df["signed_turn"] = _turn_delta(df)
    df["turn_deg"] = df["signed_turn"].abs()
    df["_cand"] = _clasificar(df)

    # Detección de lances por zarpe (puede haber varios por viaje).
    df["behavior"] = "transito"
    df.loc[df["_cand"], "behavior"] = "candidato"
    df["is_haul"] = 0
    df["haul_index"] = pd.NA  # 1..n_hauls para los pings de cada lance

    filas_resumen = []
    n_localizados = 0
    n_confiables = 0
    n_lances_total = 0
    for zid, sub in df.groupby("zarpe_id", sort=True):
        meta = sub.iloc[0]
        tons = tons_por_zarpe.get(zid, pd.NA)
        principal = principal_por_zarpe.get(zid, pd.NA)
        cand = sub[sub["_cand"]]
        bouts = _bouts_candidatos(cand)  # ordenados: lances circulares primero

        if not bouts:
            filas_resumen.append({
                "zarpe_id": zid, "rpa": meta["rpa"], "vessel_code": meta["vessel_code"],
                "vessel_name": meta["vessel_name"], "jack_mackerel_tons": tons,
                "principal_catch": principal, "n_hauls": 0,
                "haul_confidence": "sin_pesca",
                "haul_lat": pd.NA, "haul_lon": pd.NA, "haul_start": pd.NA, "haul_end": pd.NA,
                "haul_duration_h": pd.NA, "haul_n_pings": 0, "haul_mean_speed_kt": pd.NA,
                "haul_net_turn_deg": pd.NA, "haul_compactness": pd.NA,
                "haul_dist_port_km": pd.NA, "nearest_port": pd.NA,
            })
            continue

        n_localizados += 1
        sets = [(idx, m) for idx, m in bouts if m["is_set"]]
        n_lances_total += len(sets)
        # Marca los lances CONFIABLES en la traza (haul_index por orden cronológico).
        for orden, (idx, _m) in enumerate(
            sorted(sets, key=lambda t: df.loc[t[0], "_dt"].min()), start=1
        ):
            df.loc[idx, "behavior"] = "pesca"
            df.loc[idx, "is_haul"] = 1
            df.loc[idx, "haul_index"] = orden

        # Lance representativo del zarpe: el más "anillo" (primero de la lista).
        # Confianza alta si es un lance circular; baja si solo es un tramo lento
        # mar adentro (se reporta igual, para no perder el zarpe con captura).
        idx_rep, m = bouts[0]
        confianza = "alta" if m["is_set"] else "baja"
        if m["is_set"]:
            n_confiables += 1
        lance = df.loc[idx_rep]
        lat, lon = lance["latitude"].mean(), lance["longitude"].mean()
        dist_km, puerto = _dist_min_puerto(lat, lon, ports)
        filas_resumen.append({
            "zarpe_id": zid, "rpa": meta["rpa"], "vessel_code": meta["vessel_code"],
            "vessel_name": meta["vessel_name"], "jack_mackerel_tons": tons,
            "principal_catch": principal, "n_hauls": len(sets),
            "haul_confidence": confianza,
            "haul_lat": round(lat, 5), "haul_lon": round(lon, 5),
            "haul_start": lance["_dt"].min(), "haul_end": lance["_dt"].max(),
            "haul_duration_h": round(
                (lance["_dt"].max() - lance["_dt"].min()).total_seconds() / 3600.0, 2),
            "haul_n_pings": int(len(lance)),
            "haul_mean_speed_kt": round(lance["speed_kt"].mean(), 2),
            "haul_net_turn_deg": round(m["net_turn"], 1),
            "haul_compactness": round(m["compactness"], 2),
            "haul_dist_port_km": round(dist_km, 3), "nearest_port": puerto,
        })

    resumen = pd.DataFrame(filas_resumen)
    for col in ["haul_start", "haul_end"]:
        resumen[col] = pd.to_datetime(resumen[col]).dt.strftime("%Y-%m-%d %H:%M:%S")

    df["turn_deg"] = df["turn_deg"].round(1)

    pings_cols = [
        "zarpe_id", "rpa", "vessel_code", "vessel_name", "radio_call_sign",
        "location_datetime", "latitude", "longitude", "heading", "speed_kt",
        "dist_port_km", "nearest_port", "turn_deg", "behavior", "is_haul", "haul_index",
    ]
    resumen_cols = [
        "zarpe_id", "vessel_code", "vessel_name", "jack_mackerel_tons", "principal_catch",
        "n_hauls", "haul_confidence", "haul_lat", "haul_lon", "haul_start", "haul_end",
        "haul_duration_h", "haul_n_pings", "haul_mean_speed_kt", "haul_net_turn_deg",
        "haul_compactness", "haul_dist_port_km", "nearest_port",
    ]

    stats = {
        "zarpes": int(resumen["zarpe_id"].nunique()),
        "localizados": n_localizados,
        "confiables": n_confiables,
        "baja_conf": n_localizados - n_confiables,
        "sin_pesca": int(resumen["zarpe_id"].nunique()) - n_localizados,
        "lances_total": n_lances_total,
        "multi_haul": int((pd.to_numeric(resumen["n_hauls"]) > 1).sum()),
        "pings_pesca": int((df["behavior"] == "pesca").sum()),
    }
    return df[pings_cols], resumen[resumen_cols], stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    # Entradas/salidas scopeadas por fuente (SOURCE): `backup` anida bajo
    # locations/backup/ y lee capture/backup/zarpes_atacama_capture.csv.
    source = active_source()
    zarpes_dir = source.scoped(DATA_DIR) / "zarpes"
    output_dir = source.scoped(DATA_DIR) / "fishing_location"
    unified_zarpes_csv = source.scoped(DATA_DIR.parent / "capture") / "zarpes_atacama_capture.csv"

    input_csv = zarpes_dir / f"locations_{FLEET_NAME}_{tag}_zarpes.csv"
    pings_csv = output_dir / f"locations_{FLEET_NAME}_{tag}_fishing.csv"
    summary_csv = output_dir / "zarpes_atacama_haul_location.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no existe {input_csv}.\n"
            "       Generá los zarpes (asignación de pings) primero con:\n"
            "           uv run python -m processing.locations.zarpes.identify_zarpes",
            file=sys.stderr,
        )
        sys.exit(1)

    if not unified_zarpes_csv.exists():
        print(
            f"ERROR: no existe {unified_zarpes_csv}.\n"
            "       Generá el dataset unificado de zarpes con captura primero con:\n"
            "           uv run python -m processing.capture.unify.unify_zarpes",
            file=sys.stderr,
        )
        sys.exit(1)

    ports = active_region().port_coords()
    df = pd.read_csv(input_csv, dtype=str)
    captura = pd.read_csv(unified_zarpes_csv, dtype=str)

    pings, resumen, stats = identificar_pesca(df, ports, captura)

    output_dir.mkdir(parents=True, exist_ok=True)
    pings.to_csv(pings_csv, index=False)
    resumen.to_csv(summary_csv, index=False)

    dist = pd.to_numeric(resumen["haul_dist_port_km"], errors="coerce").dropna()
    dist_line = (
        f"Distancia del lance a puerto (km) — mediana: {dist.median():.1f}"
        if not dist.empty else "Distancia del lance a puerto: sin lances"
    )
    print(
        f"Identificando la ubicación del lance (velocidad + geometría circular, arte cerco)\n"
        f"  Entrada: {input_csv}\n"
        f"  Ventana de pesca: {FISHING_SPEED_MIN_KT}-{FISHING_SPEED_MAX_KT} kt, "
        f"giro neto >= {NET_TURN_MIN_DEG}° o compacidad >= {COMPACT_MIN}, "
        f"mar adentro >= {OFFSHORE_MIN_KM} km\n\n"
        f"Zarpes de entrada:            {stats['zarpes']:,}\n"
        f"  ubicación identificada:     {stats['localizados']:,}\n"
        f"    confianza alta (anillo):  {stats['confiables']:,}\n"
        f"    confianza baja (lento):   {stats['baja_conf']:,}\n"
        f"  sin pesca detectable:       {stats['sin_pesca']:,}\n"
        f"  con >1 lance (multi-haul):  {stats['multi_haul']:,}\n"
        f"Lances confiables (total):    {stats['lances_total']:,}\n"
        f"Pings etiquetados como pesca: {stats['pings_pesca']:,}\n"
        f"{dist_line}\n"
        f"Archivos escritos:\n"
        f"  (intermedio) {pings_csv}\n"
        f"  (producto final) {summary_csv}"
    )


if __name__ == "__main__":
    main()
