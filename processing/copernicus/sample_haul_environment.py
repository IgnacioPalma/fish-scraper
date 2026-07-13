"""
Anexa a cada lance (haul) las variables oceánicas de Copernicus muestreadas en
el punto y día del lance, para alimentar el modelo bayesiano de jurel.

Toma la ubicación de lance por zarpe de `data/processing/locations/single_haul/zarpes_atacama_haul_single.csv`
(el conjunto LIMPIO de modelado: zarpes con un único lance confiable, `haul_confidence
== "alta"` y `n_hauls == 1`; ver `processing.locations.single_haul.filter_single_haul`)
y le agrega las covariables ambientales, leídas de las grillas ya descargadas
en `data/copernicus/` (paquete `processing.copernicus`):

  columna salida            producto   var en el .nc     transformación
  --------------            --------   --------------     --------------
  sst_c                     SST        analysed_sst       Kelvin → °C  (− 273.15)
  chl_mg_m3                 CHL        CHL                identidad (ya en mg/m³)
  mld_m                     PHY        mlotst             identidad (m)
  sss_psu                   PHY        so_0m              identidad (salinidad superficial, PSU)
  o2_min_mmol_m3            BGC        o2_min_0_200m      identidad (mín. O₂ 0–200 m, techo OMZ)
  sst_front_c_per_km        SST        analysed_sst       |∇SST| (°C/km, frente térmico)
  chl_front_mg_m3_per_km    CHL        CHL                |∇CHL| ((mg/m³)/km, frente de clorofila)
  wind_stress_pa            WIND       east/northward_wind  τ = ρ·C_d·|U|² (Pa)
  wind_stress_east_pa       WIND       eastward_wind      componente zonal de τ (Pa)
  wind_stress_north_pa      WIND       northward_wind     componente meridional de τ (Pa)
  moon_illumination         —          (fecha del lance)  fracción iluminada del disco lunar [0,1]

Las tres familias nuevas indexan procesos de agregación del jurel: los FRENTES
(gradientes horizontales de SST y CHL) marcan bordes de masas de agua donde se
concentra el alimento; el ESFUERZO DEL VIENTO forza el afloramiento costero de
Humboldt; y la FASE LUNAR modula la captabilidad del cerco (el jurel se hunde en
noches de luna llena). La fase lunar sólo depende de la fecha (no se descarga) y
el viento es un producto aparte con cobertura propia, por eso lleva su propia
auditoría (wind_status / wind_time / wind_cell_dist_km).

Las covariables oceánicas base covarían con la literatura de jurel en Humboldt: la
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
  data/processing/locations/single_haul/zarpes_atacama_haul_single.csv
  data/copernicus/{sst,chl,phy,bgc,wind}_atacama_*.nc   (se globa por producto; tolera
      el archivo de un año y el multi-año a la vez)

Salida:
  data/output/zarpes_<region>_haul_env.csv
      → la tabla de lances + las covariables de arriba
        + auditoría oceánica: env_time (día de grilla usado), env_cell_dist_km (máx.
        distancia a una celda muestreada; 0 si todas fueron la más cercana) y env_status
        + auditoría de viento: wind_time, wind_cell_dist_km, wind_status.

Uso:
    uv run python -m processing.copernicus.sample_haul_environment
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from processing.utils.datasets import active_source
from processing.utils.regions import active_region

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "output"
COPERNICUS_DIR = Path(__file__).resolve().parents[2] / "data" / "copernicus"
_LOCATIONS_DIR = Path(__file__).resolve().parents[2] / "data" / "processing" / "locations"

EARTH_RADIUS_KM = 6371.0
KM_PER_DEG = 111.195  # km por grado de latitud (y de longitud en el ecuador)
# Radio máximo para reemplazar una celda en tierra por la celda de mar más cercana.
MAX_FALLBACK_KM = 25.0
# Tolerancia temporal: dentro de cobertura, el día más cercano queda a <= 12 h; este
# margen distingue eso de un lance fuera del rango descargado (días/meses de distancia).
TIME_TOL = pd.Timedelta(days=2)

# Esfuerzo del viento (fórmula bulk τ = ρ_air · C_d · |U| · U): densidad del aire y
# coeficiente de arrastre constante (aproximación estándar para el viento a 10 m).
RHO_AIR = 1.22    # kg/m³
DRAG_COEF = 1.3e-3

# Fase lunar: instante de una luna nueva de referencia (UTC) y mes sinódico medio.
# Basta para una covariable (error < ~0.02 en la fracción iluminada).
_MOON_NEW_REF = pd.Timestamp("2000-01-06 18:14:00")
_SYNODIC_MONTH = 29.530588853  # días

# Variables muestreadas como VALOR PUNTUAL en la celda del lance.
# (base del archivo, variable en el .nc, columna de salida, transformación)
POINT_PRODUCTS = [
    ("sst_atacama", "analysed_sst", "sst_c", lambda x: x - 273.15),
    ("chl_atacama", "CHL", "chl_mg_m3", None),
    ("phy_atacama", "mlotst", "mld_m", None),
    ("phy_atacama", "so_0m", "sss_psu", None),
    ("bgc_atacama", "o2_min_0_200m", "o2_min_mmol_m3", None),
]

# FRENTES oceánicos: magnitud del gradiente horizontal |∇campo| (unidades/km),
# muestreada en la celda del lance. Indexa frentes térmicos y de clorofila, donde
# se agrega el jurel. El gradiente en Kelvin == en °C (el offset constante no afecta
# la derivada), así que sst_front queda en °C/km sin transformación.
# (base del archivo, variable en el .nc, columna de salida)
GRADIENT_PRODUCTS = [
    ("sst_atacama", "analysed_sst", "sst_front_c_per_km"),
    ("chl_atacama", "CHL", "chl_front_mg_m3_per_km"),
]

# Grilla de viento (base): se muestrean las dos componentes y luego se deriva el
# esfuerzo del viento; las componentes crudas no se emiten como columnas.
WIND_BASE = "wind_atacama"

# Severidad de cada estado (se queda el peor por fila).
_STATUS_RANK = {"ok": 0, "fallback": 1, "fuera_de_rango": 2}


def _haversine(lat1, lon1, lat2, lon2):
    """Distancia haversine en km (escalares o arrays). Igual que en fishing_location."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _abrir_producto(base: str, *, requerido: bool = True) -> xr.Dataset | None:
    """Une todos los `<base>_*.nc` de data/copernicus en un Dataset por tiempo.

    Tolera que coexistan el archivo de un año (`_2023.nc`) y el multi-año
    (`_2023_2024.nc`): concatena por tiempo, ordena y deja un día por tiempo
    (el último, que proviene del archivo de mayor cobertura).

    Con `requerido=False`, si no hay ninguna grilla, avisa y devuelve `None` en vez
    de abortar — para capas opcionales (viento) cuya ausencia sólo deja columnas
    nulas, sin tumbar todo el muestreo (p. ej. el chequeo semanal en CI antes de que
    refresh-copernicus cachee la capa en R2)."""
    paths = sorted(COPERNICUS_DIR.glob(f"{base}_*.nc"))
    if not paths:
        msg = (
            f"No se encontró ninguna grilla `{base}_*.nc` en {COPERNICUS_DIR}.\n"
            f"Generala con `uv run python -m processing.copernicus.download_"
            f"{base.split('_')[0]}` antes de muestrear."
        )
        if requerido:
            sys.exit(msg)
        print(f"AVISO: {msg}\n       Se omite esta capa (sus columnas quedan nulas).",
              file=sys.stderr)
        return None
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


def _campo_dia(da: xr.DataArray, ts: pd.Timestamp):
    """Selecciona el día de grilla más cercano a `ts`. Devuelve (campo_2d, t_grilla),
    con `campo_2d == None` si el lance cae fuera de TIME_TOL (fuera del rango
    descargado)."""
    campo = da.sel(time=ts, method="nearest")
    t_grilla = pd.Timestamp(campo["time"].values)
    if abs(t_grilla - ts) > TIME_TOL:
        return None, t_grilla
    return campo, t_grilla


def _muestrear_celda(campo: xr.DataArray, lat: float, lon: float):
    """Muestrea un campo 2-D (ya seleccionado en tiempo) en (lat, lon) con el mismo
    fallback costero del resto del pipeline. Devuelve (valor, distancia_km, estado),
    `estado` ∈ {ok, fallback}. `valor`/`distancia` pueden ser NaN."""
    celda = campo.sel(latitude=lat, longitude=lon, method="nearest")
    valor = float(celda.values)
    if np.isfinite(valor):
        return valor, 0.0, "ok"

    # Celda más cercana en tierra/enmascarada → buscar la celda de mar válida más cercana.
    arr = np.asarray(campo.values)
    finita = np.isfinite(arr)
    if not finita.any():
        return np.nan, np.nan, "fallback"
    lon_grid, lat_grid = np.meshgrid(campo["longitude"].values, campo["latitude"].values)
    dist = _haversine(lat, lon, lat_grid[finita], lon_grid[finita])
    i = int(np.argmin(dist))
    if dist[i] > MAX_FALLBACK_KM:
        return np.nan, np.nan, "fallback"
    return float(arr[finita][i]), float(dist[i]), "fallback"


def _muestrear(da: xr.DataArray, ts: pd.Timestamp, lat: float, lon: float):
    """Muestrea una variable en (ts, lat, lon).

    Devuelve (valor, distancia_km, estado, tiempo_grilla). `valor`/`distancia` pueden
    ser NaN. `estado` ∈ {ok, fallback, fuera_de_rango}."""
    campo, t_grilla = _campo_dia(da, ts)
    if campo is None:
        return np.nan, np.nan, "fuera_de_rango", t_grilla
    valor, dist, estado = _muestrear_celda(campo, lat, lon)
    return valor, dist, estado, t_grilla


def _gradiente_2d(campo: xr.DataArray) -> xr.DataArray:
    """Magnitud del gradiente horizontal |∇campo| (unidades/km) de un campo 2-D
    (lat × lon), por diferencias finitas. Índice de frentes oceánicos.

    La grilla es regular en grados; el paso en km es constante en latitud
    (KM_PER_DEG) y varía con el coseno de la latitud en longitud. Las celdas de
    tierra (NaN) propagan NaN a sus vecinas, así que el borde tierra-mar queda NaN
    y el muestreo lo resuelve con el mismo fallback costero que el resto."""
    campo = campo.transpose("latitude", "longitude")
    lat = campo["latitude"].values
    lon = campo["longitude"].values
    dy_km = float(np.abs(np.diff(lat)).mean()) * KM_PER_DEG
    dx_km = float(np.abs(np.diff(lon)).mean()) * KM_PER_DEG * np.cos(np.radians(lat))
    arr = np.asarray(campo.values, dtype="float64")
    gy = np.gradient(arr, axis=0) / dy_km
    gx = np.gradient(arr, axis=1) / dx_km[:, np.newaxis]
    mag = np.sqrt(gx**2 + gy**2)
    return xr.DataArray(mag, coords=campo.coords, dims=campo.dims, name=campo.name)


def _muestrear_frente(da: xr.DataArray, ts: pd.Timestamp, lat: float, lon: float):
    """Como `_muestrear` pero devuelve |∇campo| (unidades/km): calcula el gradiente
    SÓLO sobre el campo 2-D del día más cercano (por corte), sin materializar el cubo
    completo — clave para no disparar el pico de memoria en regiones grandes."""
    campo, t_grilla = _campo_dia(da, ts)
    if campo is None:
        return np.nan, np.nan, "fuera_de_rango", t_grilla
    valor, dist, estado = _muestrear_celda(_gradiente_2d(campo), lat, lon)
    return valor, dist, estado, t_grilla


def _moon_illumination(ts: pd.Timestamp) -> float:
    """Fracción iluminada del disco lunar en la fecha `ts` (0 = luna nueva,
    1 = luna llena), a partir del mes sinódico medio."""
    days = (ts - _MOON_NEW_REF) / pd.Timedelta(days=1)
    phase = (days % _SYNODIC_MONTH) / _SYNODIC_MONTH  # 0 = nueva, 0.5 = llena
    return float((1 - np.cos(2 * np.pi * phase)) / 2)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)

    # Rutas scopeadas por fuente (SOURCE), resueltas en tiempo de ejecución para que
    # run_all pueda alternar SOURCE en el mismo proceso. `backup` lee
    # locations/backup/single_haul/ y escribe zarpes_<region>_backup_haul_env.csv.
    source = active_source()
    HAUL_CSV = source.scoped(_LOCATIONS_DIR) / "single_haul" / "zarpes_atacama_haul_single.csv"
    OUTPUT_CSV = OUTPUT_DIR / f"zarpes_{active_region().key}{source.output_suffix()}_haul_env.csv"

    if not HAUL_CSV.exists():
        sys.exit(
            f"No se encontró la tabla de lances: {HAUL_CSV}\n"
            "       Generala primero con:\n"
            "           uv run python -m processing.locations.single_haul.filter_single_haul"
        )

    hauls = pd.read_csv(HAUL_CSV)
    hauls["haul_start"] = pd.to_datetime(hauls["haul_start"], errors="coerce")

    # Abrir cada grilla base una sola vez. El viento es un producto aparte con su
    # propia cobertura, así que lleva su propia auditoría (wind_status/…).
    ocean_bases = {b for b, *_ in POINT_PRODUCTS} | {b for b, _, _ in GRADIENT_PRODUCTS}
    print(f"Abriendo grillas Copernicus para: {', '.join(sorted(ocean_bases | {WIND_BASE}))}")
    grillas = {base: _abrir_producto(base) for base in ocean_bases}
    # El viento es opcional: si su grilla aún no está (p. ej. CI antes del refresh),
    # el esfuerzo del viento queda nulo con wind_status="sin_grilla" en vez de abortar.
    wind_ds = _abrir_producto(WIND_BASE, requerido=False)

    # Muestreadores oceánicos: (columna, DataArray, tipo, transformación). Los frentes
    # (`frente`) muestrean |∇campo| calculado por corte diario sobre las mismas grillas
    # SST/CHL, así que comparten su cobertura temporal y caen bajo el mismo env_status.
    ocean_samplers = [
        (col, grillas[base][var], "punto", transform)
        for base, var, col, transform in POINT_PRODUCTS
    ]
    ocean_samplers += [
        (col, grillas[base][var], "frente", None) for base, var, col in GRADIENT_PRODUCTS
    ]

    ocean_cols = [col for col, *_ in ocean_samplers]
    resultados = {col: [] for col in ocean_cols}
    wind_stress, wind_stress_e, wind_stress_n, moon = [], [], [], []
    env_status, env_dist, env_time = [], [], []
    wind_status, wind_dist, wind_time = [], [], []

    for _, row in hauls.iterrows():
        lat, lon, ts = row["haul_lat"], row["haul_lon"], row["haul_start"]

        # La fase lunar sólo depende de la fecha del lance.
        moon.append(_moon_illumination(ts) if pd.notna(ts) else np.nan)

        if pd.isna(lat) or pd.isna(lon) or pd.isna(ts):
            for col in ocean_cols:
                resultados[col].append(np.nan)
            env_status.append("sin_coords"), env_dist.append(np.nan), env_time.append(pd.NaT)
            wind_stress.append(np.nan), wind_stress_e.append(np.nan), wind_stress_n.append(np.nan)
            wind_status.append("sin_coords"), wind_dist.append(np.nan), wind_time.append(pd.NaT)
            continue

        lat, lon = float(lat), float(lon)

        # --- Covariables oceánicas (puntuales + frentes) ---
        peor, max_dist, t_usado = "ok", 0.0, pd.NaT
        for col, da, tipo, transform in ocean_samplers:
            muestrear = _muestrear_frente if tipo == "frente" else _muestrear
            valor, dist, estado, t_grilla = muestrear(da, ts, lat, lon)
            if transform is not None and np.isfinite(valor):
                valor = transform(valor)
            resultados[col].append(valor)
            if _STATUS_RANK[estado] > _STATUS_RANK[peor]:
                peor = estado
            if np.isfinite(dist):
                max_dist = max(max_dist, dist)
            if pd.isna(t_usado):
                t_usado = t_grilla
        env_status.append(peor), env_dist.append(max_dist), env_time.append(t_usado)

        # --- Esfuerzo del viento (τ = ρ_air · C_d · |U| · U por componente) ---
        if wind_ds is None:
            wind_stress.append(np.nan), wind_stress_e.append(np.nan), wind_stress_n.append(np.nan)
            wind_status.append("sin_grilla"), wind_dist.append(np.nan), wind_time.append(pd.NaT)
        else:
            u, du, su, tu = _muestrear(wind_ds["eastward_wind"], ts, lat, lon)
            v, dv, sv, tv = _muestrear(wind_ds["northward_wind"], ts, lat, lon)
            if np.isfinite(u) and np.isfinite(v):
                k = RHO_AIR * DRAG_COEF * np.hypot(u, v)
                wind_stress.append(k * np.hypot(u, v))
                wind_stress_e.append(k * u)
                wind_stress_n.append(k * v)
            else:
                wind_stress.append(np.nan), wind_stress_e.append(np.nan), wind_stress_n.append(np.nan)
            wind_status.append(su if _STATUS_RANK[su] >= _STATUS_RANK[sv] else sv)
            dists = [d for d in (du, dv) if np.isfinite(d)]
            wind_dist.append(max(dists) if dists else np.nan)
            wind_time.append(tu if pd.notna(tu) else tv)

    for col in ocean_cols:
        hauls[col] = resultados[col]
    hauls["wind_stress_pa"] = wind_stress
    hauls["wind_stress_east_pa"] = wind_stress_e
    hauls["wind_stress_north_pa"] = wind_stress_n
    hauls["moon_illumination"] = moon
    hauls["env_time"] = pd.to_datetime(pd.Series(env_time)).dt.strftime("%Y-%m-%d")
    hauls["env_cell_dist_km"] = np.round(env_dist, 3)
    hauls["env_status"] = env_status
    hauls["wind_time"] = pd.to_datetime(pd.Series(wind_time)).dt.strftime("%Y-%m-%d")
    hauls["wind_cell_dist_km"] = np.round(pd.Series(wind_dist, dtype="float64"), 3)
    hauls["wind_status"] = wind_status

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    hauls.to_csv(OUTPUT_CSV, index=False)

    # --- Resumen ----------------------------------------------------------
    display_cols = ocean_cols + [
        "wind_stress_pa", "wind_stress_east_pa", "wind_stress_north_pa", "moon_illumination",
    ]
    print(f"\nLances procesados: {len(hauls)}")
    print("Estado oceánico (env_status):")
    for estado, n in hauls["env_status"].value_counts().items():
        print(f"  {estado:>15}: {n}")
    print("Estado viento (wind_status):")
    for estado, n in hauls["wind_status"].value_counts().items():
        print(f"  {estado:>15}: {n}")
    print("Variables ambientales (mín / media / máx sobre valores no nulos):")
    for col in display_cols:
        s = hauls[col].dropna()
        if len(s):
            print(f"  {col:>22}: {s.min():.3f} / {s.mean():.3f} / {s.max():.3f}  (n={len(s)})")
        else:
            print(f"  {col:>22}: sin datos")
    fb = hauls.loc[hauls["env_status"] == "fallback", "env_cell_dist_km"]
    if len(fb):
        print(f"Fallback costero (océano): {len(fb)} lances, distancia máx {fb.max():.2f} km")
    print(f"\nArchivo generado:\n  {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
