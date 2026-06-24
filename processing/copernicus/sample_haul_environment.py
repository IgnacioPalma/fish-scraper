"""
Anexa a cada lance (haul) las variables oceánicas de Copernicus muestreadas en
el punto y día del lance, para alimentar el modelo bayesiano de jurel.

Toma la ubicación de lance por zarpe de `data/output/zarpes_atacama_haul_single.csv`
(el conjunto LIMPIO de modelado: zarpes con un único lance confiable, `haul_confidence
== "alta"` y `n_hauls == 1`; ver `processing.locations.single_haul.filter_single_haul`)
y le agrega cinco covariables ambientales, leídas de las grillas ya descargadas
en `data/copernicus/` (paquete `processing.copernicus`):

  columna salida     producto   var en el .nc     transformación
  --------------     --------   --------------     --------------
  sst_c              SST        analysed_sst       Kelvin → °C  (− 273.15)
  chl_mg_m3          CHL        CHL                identidad (ya en mg/m³)
  mld_m              PHY        mlotst             identidad (m)
  sss_psu            PHY        so_0m              identidad (salinidad superficial, PSU)
  o2_min_mmol_m3     BGC        o2_min_0_200m      identidad (mín. O₂ 0–200 m, techo OMZ)

Las dos últimas covarían con la literatura de jurel en el sistema de Humboldt: la
salinidad superficial discrimina masas de agua (frente subtropical) y el mínimo de
O₂ en la columna 0–200 m indexa el techo de la OMZ, que comprime el hábitat pelágico.
Ambas son superficiales / integradas en la vertical, así que NO sufren el enmascarado
costero por profundidad que llevó a descartar la temperatura subsuperficial `thetao`.

Las grillas son productos L4 (rellenados) o reanálisis, así que las nubes NO son
fuente de huecos: las únicas celdas NaN son la máscara de tierra. Eso sí importa
para los lances cerca de la costa, porque la celda más cercana de ~4 km puede caer
en tierra. Por eso, si la celda más cercana es NaN, se busca la celda de mar válida
más cercana dentro de MAX_FALLBACK_KM y se registra su distancia.

Muestreo (por lance, por variable):
  1. Día más cercano: `da.sel(time=haul_start, method="nearest")`. Si el lance cae
     fuera del rango temporal de la grilla (> TIME_TOL) → `fuera_de_rango`, valor nulo.
  2. Celda más cercana: `.sel(latitude, longitude, method="nearest")`. Si trae valor
     finito se usa (distancia 0).
  3. Si es NaN (tierra/máscara): celda de mar válida más cercana por haversine, dentro
     de MAX_FALLBACK_KM → `fallback` (se registra la distancia). Si ninguna entra en el
     radio → valor nulo para esa variable.

Los lances sin coordenadas (`haul_lat`/`haul_lon` nulos) se conservan con las cuatro
variables nulas y `env_status == "sin_coords"`.

Entrada:
  data/output/zarpes_atacama_haul_single.csv
  data/copernicus/{sst,chl,phy}_atacama_*.nc   (se globa por producto; tolera el
      archivo de un año y el multi-año a la vez)

Salida:
  data/output/zarpes_atacama_haul_env.csv
      → la tabla de lances + sst_c, chl_mg_m3, mld_m, temp_400m_c
        + auditoría: env_time (día de grilla usado), env_cell_dist_km (máx. distancia
        a una celda muestreada; 0 si todas fueron la más cercana) y env_status.

Uso:
    uv run python -m processing.copernicus.sample_haul_environment
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "output"
COPERNICUS_DIR = Path(__file__).resolve().parents[2] / "data" / "copernicus"
HAUL_CSV = OUTPUT_DIR / "zarpes_atacama_haul_single.csv"
OUTPUT_CSV = OUTPUT_DIR / "zarpes_atacama_haul_env.csv"

EARTH_RADIUS_KM = 6371.0
# Radio máximo para reemplazar una celda en tierra por la celda de mar más cercana.
MAX_FALLBACK_KM = 25.0
# Tolerancia temporal: dentro de cobertura, el día más cercano queda a <= 12 h; este
# margen distingue eso de un lance fuera del rango descargado (días/meses de distancia).
TIME_TOL = pd.Timedelta(days=2)

# (base del archivo, variable en el .nc, columna de salida, transformación)
PRODUCTS = [
    ("sst_atacama", "analysed_sst", "sst_c", lambda x: x - 273.15),
    ("chl_atacama", "CHL", "chl_mg_m3", None),
    ("phy_atacama", "mlotst", "mld_m", None),
    ("phy_atacama", "so_0m", "sss_psu", None),
    ("bgc_atacama", "o2_min_0_200m", "o2_min_mmol_m3", None),
]

# Severidad de cada estado (se queda el peor por fila).
_STATUS_RANK = {"ok": 0, "fallback": 1, "fuera_de_rango": 2}


def _haversine(lat1, lon1, lat2, lon2):
    """Distancia haversine en km (escalares o arrays). Igual que en fishing_location."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _abrir_producto(base: str) -> xr.Dataset:
    """Une todos los `<base>_*.nc` de data/copernicus en un Dataset por tiempo.

    Tolera que coexistan el archivo de un año (`_2023.nc`) y el multi-año
    (`_2023_2024.nc`): concatena por tiempo, ordena y deja un día por tiempo
    (el último, que proviene del archivo de mayor cobertura)."""
    paths = sorted(COPERNICUS_DIR.glob(f"{base}_*.nc"))
    if not paths:
        sys.exit(
            f"No se encontró ninguna grilla `{base}_*.nc` en {COPERNICUS_DIR}.\n"
            f"Generala con `uv run python -m processing.copernicus.download_"
            f"{base.split('_')[0]}` antes de muestrear."
        )
    datasets = [xr.open_dataset(p) for p in paths]
    # `join="exact"` exige que todos los archivos compartan exactamente la grilla
    # destino común (lat/lon): si alguno trae otra grilla (p.ej. un descargado crudo
    # `_(1).nc` que quedó por una descarga interrumpida), falla en vez de alinear con
    # join externo y rellenar NaN en silencio.
    ds = (
        xr.concat(datasets, dim="time", join="exact")
        if len(datasets) > 1
        else datasets[0]
    )
    ds = ds.sortby("time").drop_duplicates("time", keep="last")
    return ds


def _muestrear(da: xr.DataArray, ts: pd.Timestamp, lat: float, lon: float):
    """Muestrea una variable en (ts, lat, lon).

    Devuelve (valor, distancia_km, estado, tiempo_grilla). `valor`/`distancia` pueden
    ser NaN. `estado` ∈ {ok, fallback, fuera_de_rango}."""
    campo = da.sel(time=ts, method="nearest")
    t_grilla = pd.Timestamp(campo["time"].values)
    if abs(t_grilla - ts) > TIME_TOL:
        return np.nan, np.nan, "fuera_de_rango", t_grilla

    celda = campo.sel(latitude=lat, longitude=lon, method="nearest")
    valor = float(celda.values)
    if np.isfinite(valor):
        return valor, 0.0, "ok", t_grilla

    # Celda más cercana en tierra/enmascarada → buscar la celda de mar válida más cercana.
    arr = campo.values
    finita = np.isfinite(arr)
    if not finita.any():
        return np.nan, np.nan, "fallback", t_grilla
    lon_grid, lat_grid = np.meshgrid(campo["longitude"].values, campo["latitude"].values)
    dist = _haversine(lat, lon, lat_grid[finita], lon_grid[finita])
    i = int(np.argmin(dist))
    if dist[i] > MAX_FALLBACK_KM:
        return np.nan, np.nan, "fallback", t_grilla
    return float(arr[finita][i]), float(dist[i]), "fallback", t_grilla


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)

    if not HAUL_CSV.exists():
        sys.exit(
            f"No se encontró la tabla de lances: {HAUL_CSV}\n"
            "       Generala primero con:\n"
            "           uv run python -m processing.locations.single_haul.filter_single_haul"
        )

    hauls = pd.read_csv(HAUL_CSV)
    hauls["haul_start"] = pd.to_datetime(hauls["haul_start"], errors="coerce")

    # Abrir cada producto una sola vez (PHY aporta dos variables).
    bases = {base for base, *_ in PRODUCTS}
    print(f"Abriendo grillas Copernicus para: {', '.join(sorted(bases))}")
    grillas = {base: _abrir_producto(base) for base in bases}

    out_cols = [col for _, _, col, _ in PRODUCTS]
    resultados = {col: [] for col in out_cols}
    env_status, env_dist, env_time = [], [], []

    for _, row in hauls.iterrows():
        lat, lon, ts = row["haul_lat"], row["haul_lon"], row["haul_start"]
        if pd.isna(lat) or pd.isna(lon) or pd.isna(ts):
            for col in out_cols:
                resultados[col].append(np.nan)
            env_status.append("sin_coords")
            env_dist.append(np.nan)
            env_time.append(pd.NaT)
            continue

        peor, max_dist, t_usado = "ok", 0.0, pd.NaT
        for base, var, col, transform in PRODUCTS:
            valor, dist, estado, t_grilla = _muestrear(
                grillas[base][var], ts, float(lat), float(lon)
            )
            if transform is not None and np.isfinite(valor):
                valor = transform(valor)
            resultados[col].append(valor)
            if _STATUS_RANK[estado] > _STATUS_RANK[peor]:
                peor = estado
            if np.isfinite(dist):
                max_dist = max(max_dist, dist)
            if pd.isna(t_usado):
                t_usado = t_grilla
        env_status.append(peor)
        env_dist.append(max_dist)
        env_time.append(t_usado)

    for col in out_cols:
        hauls[col] = resultados[col]
    hauls["env_time"] = pd.to_datetime(pd.Series(env_time)).dt.strftime("%Y-%m-%d")
    hauls["env_cell_dist_km"] = np.round(env_dist, 3)
    hauls["env_status"] = env_status

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hauls.to_csv(OUTPUT_CSV, index=False)

    # --- Resumen ----------------------------------------------------------
    print(f"\nLances procesados: {len(hauls)}")
    print("Estado (env_status):")
    for estado, n in hauls["env_status"].value_counts().items():
        print(f"  {estado:>15}: {n}")
    print("Variables ambientales (mín / media / máx sobre valores no nulos):")
    for col in out_cols:
        s = hauls[col].dropna()
        if len(s):
            print(f"  {col:>12}: {s.min():.3f} / {s.mean():.3f} / {s.max():.3f}  (n={len(s)})")
        else:
            print(f"  {col:>12}: sin datos")
    fb = hauls.loc[hauls["env_status"] == "fallback", "env_cell_dist_km"]
    if len(fb):
        print(f"Fallback costero: {len(fb)} lances, distancia máx {fb.max():.2f} km")
    print(f"\nArchivo generado:\n  {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
