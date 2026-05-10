"""
Cruza data/ships_filtered.csv contra los NetCDF descargados (SST, CHL,
PHY, BGC, SLA, WIND) y exporta data/ships_enriched.csv con la
observación más cercana en espacio para el día del zarpe.

Para cada lance se busca, dentro de la grilla de 1/24° (≈4 km), la
celda más cercana donde existan SIMULTÁNEAMENTE SST y CHL no-nulas ese
día (validez "primaria"). El resto de variables (MLD, salinidad,
oxígeno, plancton, anomalía altimétrica, vientos…) se muestrean en
esa misma celda; sus NaN coastal/land se propagan tal cual al CSV.

Lances fuera del bounding box, sin coordenadas, sin fecha UTC válida o
en días totalmente cubiertos por nubes/tierra quedan con NaN en las
columnas nuevas (no abortan).

Si alguno de los NetCDF opcionales (PHY, BGC, SLA, WIND) no existe,
se imprime un aviso por stderr y el script sigue: las columnas
correspondientes quedan NaN. Esto preserva la compatibilidad con un
flujo histórico que sólo haya descargado SST y CHL.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.spatial import cKDTree

from utils.cmems_common import TARGET_LAT, TARGET_LON


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_CSV = DATA_DIR / "ships_filtered.csv"
SST_NC = DATA_DIR / "sst_atacama_2017_2022.nc"
CHL_NC = DATA_DIR / "chl_atacama_2017_2022.nc"
OUTPUT_CSV = DATA_DIR / "ships_enriched.csv"

# NetCDFs opcionales: si están presentes se mergean al Dataset común;
# si faltan, se imprime un aviso y se siguen sin esa familia.
OPTIONAL_NETCDFS: dict[str, str] = {
    "phy_atacama_2017_2022.nc": "PHY (MLD/salinidad/temp 400 m)",
    "bgc_atacama_2017_2022.nc": "BGC (O₂/zooplancton/fitoplancton/NPP)",
    "sla_atacama_2017_2022.nc": "SLA (altimetría/corrientes geostróficas)",
    "wind_atacama_2017_2022.nc": "WIND (vientos a 10 m)",
}

# Bounding box de la grilla (idéntico al de los descargadores).
LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

# Rango temporal cubierto por los NetCDF.
DATE_MIN = "2017-01-01"
DATE_MAX = "2022-12-31"

# Proyección equirectangular local: a -27° de latitud, 1° lon ≈ 99 km y
# 1° lat ≈ 111 km. Escalar la longitud por cos(LAT_REF) elimina el sesgo
# del ~11% de hacer KDTree directamente sobre grados — más simple que
# haversine y con error <0.5% sobre el bbox de Atacama.
LAT_REF = -27.0
SCALE_LON = math.cos(math.radians(LAT_REF))
DEG_TO_KM = 111.32

REQUIRED_COLUMNS = ("LATITUD_DD", "LONGITUD_DD", "FECHA_HORA_ZARPE_UTC")

# Columnas posicionales que el enriquecimiento agrega siempre (las
# columnas de valor dependen de qué NetCDFs estén presentes y se
# determinan en tiempo de ejecución a partir del Dataset combinado).
GRID_COLUMNS = ("LAT_GRILLA", "LON_GRILLA", "DISTANCIA_KM_GRILLA")

# Variables "primarias" para construir el árbol de celdas válidas: una
# celda califica sólo si AMBAS están presentes ese día. Las demás
# variables se muestrean en esas celdas aunque sean NaN allí.
PRIMARY_VARS = ("analysed_sst_celsius", "chl_mg_m3")


def load_grid_dataset() -> xr.Dataset:
    """Carga SST y CHL (obligatorios) y, si están presentes, los
    NetCDFs opcionales de PHY, BGC, SLA y WIND. Devuelve un único
    Dataset combinado sobre la grilla compartida.

    SST llega en Kelvin en el .nc (download_sst.py reescribe el NetCDF
    antes de la conversión a Celsius del CSV); aquí convertimos a °C
    y renombramos para que los nombres del Dataset coincidan con los
    de los CSV downstream.
    """
    if not SST_NC.exists():
        print(
            f"ERROR: no se encontró {SST_NC}.\n"
            "       Ejecuta `docker compose run --rm download_sst` antes "
            "de enriquecer.",
            file=sys.stderr,
        )
        sys.exit(2)
    if not CHL_NC.exists():
        print(
            f"ERROR: no se encontró {CHL_NC}.\n"
            "       Ejecuta `docker compose run --rm download_chl` antes "
            "de enriquecer.",
            file=sys.stderr,
        )
        sys.exit(2)

    with xr.open_dataset(SST_NC, engine="netcdf4") as sst_raw:
        sst = sst_raw.load()
    with xr.open_dataset(CHL_NC, engine="netcdf4") as chl_raw:
        chl = chl_raw.load()

    if "analysed_sst" not in sst.variables:
        print(
            "ERROR: el NetCDF de SST no contiene la variable `analysed_sst`. "
            "       ¿El archivo fue regenerado con un dataset distinto?",
            file=sys.stderr,
        )
        sys.exit(2)
    if "CHL" not in chl.variables:
        print(
            "ERROR: el NetCDF de CHL no contiene la variable `CHL`. "
            "       ¿El archivo fue regenerado con un dataset distinto?",
            file=sys.stderr,
        )
        sys.exit(2)

    arrays: list[xr.DataArray] = [
        (sst["analysed_sst"] - 273.15).rename("analysed_sst_celsius"),
        chl["CHL"].rename("chl_mg_m3"),
    ]

    # NetCDFs opcionales. Si alguno falta, lo decimos por stderr y
    # continuamos: las columnas correspondientes quedarán NaN en el
    # CSV final.
    for filename, label in OPTIONAL_NETCDFS.items():
        path = DATA_DIR / filename
        if not path.exists():
            print(
                f"AVISO: no se encontró {path.name} ({label}). "
                "Las columnas correspondientes quedarán NaN.",
                file=sys.stderr,
            )
            continue
        with xr.open_dataset(path, engine="netcdf4") as extra_raw:
            extra = extra_raw.load()
        for vname in extra.data_vars:
            arrays.append(extra[vname])

    # join="outer" tolera NetCDFs con cobertura temporal ligeramente
    # distinta (rellena con NaN los días que no estén en todos).
    # compat="override" evita conflictos por atributos cuando dos
    # archivos describen la misma coord con metadatos distintos.
    return xr.merge(arrays, join="outer", compat="override")


def load_ships(path: Path) -> pd.DataFrame:
    """Lee ships_filtered.csv (sep=';', dtype=str) y castea las columnas
    numéricas y de fecha al tipo correcto. Aborta si faltan columnas.
    """
    if not path.exists():
        print(
            f"ERROR: no se encontró {path}.\n"
            "       Ejecuta `docker compose run --rm filter_ships` primero.",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(path, sep=";", dtype=str, low_memory=False)

    faltantes = set(REQUIRED_COLUMNS) - set(df.columns)
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en {path.name}: "
            f"{sorted(faltantes)}.\n"
            "       Reejecuta `filter_ships` con la versión actualizada.",
            file=sys.stderr,
        )
        sys.exit(2)

    df["LATITUD_DD"] = pd.to_numeric(df["LATITUD_DD"], errors="coerce")
    df["LONGITUD_DD"] = pd.to_numeric(df["LONGITUD_DD"], errors="coerce")
    return df


def is_in_bbox(lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Booleano por fila: ¿(lat, lon) cae dentro del bbox de la grilla?"""
    return (
        lat.between(LAT_MIN, LAT_MAX, inclusive="both")
        & lon.between(LON_MIN, LON_MAX, inclusive="both")
    )


def project_xy(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Proyección equirectangular local centrada en LAT_REF.

    Devuelve una matriz (N, 2) con columnas [x = lon * cos(LAT_REF), y = lat].
    Las distancias euclidianas en este espacio aproximan grados de gran
    círculo con error <0.5% sobre el bbox de Atacama.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    return np.column_stack([lon * SCALE_LON, lat])


def _squeeze_2d(arr: np.ndarray) -> np.ndarray:
    """Si `.sel(time=str)` dejó la dim time con tamaño 1, nos quedamos
    con la primera lámina (lat, lon) para que el resto sea 2-D."""
    return arr[0] if arr.ndim == 3 else arr


def build_day_tree(ds_day: xr.Dataset):
    """Para un slice de un día, devuelve (tree, lat_valid, lon_valid,
    valid_arrays) donde valid_arrays es {nombre_variable: array 1-D}
    alineado en orden con los puntos del cKDTree.

    El árbol se construye sólo sobre celdas con SST y CHL no-nulas
    simultáneamente (validez primaria). El resto de variables se
    muestrean en esas mismas celdas; sus posibles NaN se propagan tal
    cual al CSV. Devuelve None si ese día no hay celdas primarias
    válidas.
    """
    sst_arr = _squeeze_2d(ds_day["analysed_sst_celsius"].values)
    chl_arr = _squeeze_2d(ds_day["chl_mg_m3"].values)

    mask = ~(np.isnan(sst_arr) | np.isnan(chl_arr))
    if not mask.any():
        return None

    lat_grid = ds_day["latitude"].values
    lon_grid = ds_day["longitude"].values
    lat_idx, lon_idx = np.where(mask)
    lat_valid = lat_grid[lat_idx]
    lon_valid = lon_grid[lon_idx]

    valid_arrays: dict[str, np.ndarray] = {}
    for vname in ds_day.data_vars:
        arr = _squeeze_2d(ds_day[vname].values)
        if arr.shape != mask.shape:
            # Variable con forma inesperada (no 2-D sobre lat/lon);
            # la saltamos para no romper el cruce.
            continue
        valid_arrays[vname] = arr[mask]

    tree = cKDTree(project_xy(lat_valid, lon_valid))
    return tree, lat_valid, lon_valid, valid_arrays


def enrich_one_day(
    ships_day: pd.DataFrame, ds_day: xr.Dataset
) -> dict[str, np.ndarray] | None:
    """Para todos los lances de un mismo día, devuelve los valores de
    las columnas nuevas alineados al índice de `ships_day`. Devuelve
    None si no hay celdas válidas ese día.
    """
    result = build_day_tree(ds_day)
    if result is None:
        return None
    tree, lat_valid, lon_valid, valid_arrays = result

    ship_xy = project_xy(
        ships_day["LATITUD_DD"].to_numpy(),
        ships_day["LONGITUD_DD"].to_numpy(),
    )
    distances, idx = tree.query(ship_xy)

    out: dict[str, np.ndarray] = {
        "LAT_GRILLA": lat_valid[idx],
        "LON_GRILLA": lon_valid[idx],
        "DISTANCIA_KM_GRILLA": distances * DEG_TO_KM,
    }
    for vname, varr in valid_arrays.items():
        out[vname] = varr[idx]
    return out


def main() -> None:
    ds = load_grid_dataset()
    df = load_ships(INPUT_CSV)

    # Las columnas de valor dependen de los NetCDFs efectivamente
    # presentes; las posicionales (LAT_GRILLA, LON_GRILLA, DISTANCIA…)
    # son siempre las mismas.
    value_columns = tuple(ds.data_vars)
    new_columns = (*GRID_COLUMNS, *value_columns)
    for col in new_columns:
        df[col] = np.nan

    m_coord = df["LATITUD_DD"].notna() & df["LONGITUD_DD"].notna()
    m_date = df["FECHA_HORA_ZARPE_UTC"].notna()
    m_bbox = is_in_bbox(df["LATITUD_DD"], df["LONGITUD_DD"])
    m_range = df["FECHA_HORA_ZARPE_UTC"].between(DATE_MIN, DATE_MAX)
    eligible = m_coord & m_date & m_bbox & m_range

    n_sin_coord = int((~m_coord).sum())
    n_sin_fecha = int((m_coord & ~m_date).sum())
    n_fuera_bbox = int((m_coord & m_date & ~m_bbox).sum())
    n_fuera_rango = int((m_coord & m_date & m_bbox & ~m_range).sum())
    n_sin_fecha_grilla = 0
    n_sin_celdas_validas = 0
    n_enriquecidas = 0

    # Pre-calcular las fechas únicas presentes en el Dataset combinado
    # para evitar KeyError ruidoso cuando un lance cae justo en un día
    # que no está cubierto (gaps esporádicos, redownloads parciales,
    # cobertura distinta entre productos).
    fechas_grilla = set(
        pd.to_datetime(ds["time"].values).strftime("%Y-%m-%d").tolist()
    )

    grouped = df.loc[eligible].groupby("FECHA_HORA_ZARPE_UTC", sort=False)
    for date_str, group in grouped:
        if date_str not in fechas_grilla:
            n_sin_fecha_grilla += len(group)
            continue

        ds_day = ds.sel(time=date_str)
        result = enrich_one_day(group, ds_day)
        if result is None:
            n_sin_celdas_validas += len(group)
            continue

        for col, vals in result.items():
            df.loc[group.index, col] = vals
        n_enriquecidas += len(group)

    df.to_csv(OUTPUT_CSV, sep=";", index=False)

    total = len(df)
    columnas_valor_str = ", ".join(value_columns) if value_columns else "(ninguna)"
    print(
        f"Filas totales:               {total:,}\n"
        f"Filas enriquecidas:          {n_enriquecidas:,}\n"
        f"Filas sin coordenada:        {n_sin_coord:,}\n"
        f"Filas sin fecha UTC:         {n_sin_fecha:,}\n"
        f"Filas fuera de bbox:         {n_fuera_bbox:,}\n"
        f"Filas fuera de rango fecha:  {n_fuera_rango:,}\n"
        f"Filas sin día en grilla:     {n_sin_fecha_grilla:,}\n"
        f"Filas sin celdas válidas:    {n_sin_celdas_validas:,}\n"
        f"Variables agregadas:         {columnas_valor_str}\n"
        f"Archivo escrito:             {OUTPUT_CSV}"
    )

    # Sanidad: las categorías de exclusión deben sumar exactamente las no enriquecidas.
    no_enriquecidas = (
        n_sin_coord
        + n_sin_fecha
        + n_fuera_bbox
        + n_fuera_rango
        + n_sin_fecha_grilla
        + n_sin_celdas_validas
    )
    if n_enriquecidas + no_enriquecidas != total:
        print(
            f"ADVERTENCIA: {n_enriquecidas} + {no_enriquecidas} != {total}. "
            "Los contadores no cierran; revisa el flujo de máscaras.",
            file=sys.stderr,
        )

    # Sanidad opcional: que TARGET_LAT/TARGET_LON coincidan con la grilla del
    # dataset (CLAUDE.md lo garantiza pero conviene fallar rápido si se rompe).
    if not (
        np.allclose(ds["latitude"].values, TARGET_LAT)
        and np.allclose(ds["longitude"].values, TARGET_LON)
    ):
        print(
            "ADVERTENCIA: la grilla del NetCDF no coincide con TARGET_LAT/"
            "TARGET_LON de utils/cmems_common.py. Las descargas podrían "
            "haber usado una grilla distinta.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
