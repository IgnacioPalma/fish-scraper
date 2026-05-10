"""
Cruza data/ships_filtered.csv contra los NetCDF de SST y CHL y exporta
data/ships_enriched.csv con la observación más cercana en espacio para
el día del zarpe.

Para cada lance se busca, dentro de la grilla de 1/24° (≈4 km), la celda
no-nula MÁS CERCANA donde existan SIMULTÁNEAMENTE SST y CHL ese día.
Lances fuera del bounding box de la grilla, sin coordenadas, sin fecha
UTC válida o en días totalmente cubiertos por nubes/tierra quedan con
NaN en las columnas nuevas (no abortan).
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
NEW_COLUMNS = (
    "LAT_GRILLA",
    "LON_GRILLA",
    "DISTANCIA_KM_GRILLA",
    "analysed_sst_celsius",
    "chl_mg_m3",
)


def load_grid_dataset() -> xr.Dataset:
    """Carga SST y CHL desde los NetCDF, convierte SST de Kelvin a Celsius
    y los fusiona en un único Dataset con variables `analysed_sst_celsius`
    y `chl_mg_m3` sobre la grilla compartida.

    Los `.nc` guardan SST en Kelvin (`analysed_sst`) y CHL bajo el nombre
    upstream `CHL`; aquí dejamos los nombres en el formato que ya usan los
    CSV downstream para que un eventual merge sea directo.
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

    sst_celsius = (sst["analysed_sst"] - 273.15).rename("analysed_sst_celsius")
    chl_named = chl["CHL"].rename("chl_mg_m3")
    return xr.merge([sst_celsius, chl_named])


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


def build_day_tree(ds_day: xr.Dataset):
    """Para un slice de un día, devuelve (tree, lat_valid, lon_valid,
    sst_valid, chl_valid) sólo sobre celdas con AMBAS variables no-nulas.
    Devuelve None si ese día la grilla está totalmente cubierta por
    nubes/tierra (cero celdas válidas).
    """
    sst_arr = ds_day["analysed_sst_celsius"].values
    chl_arr = ds_day["chl_mg_m3"].values

    # `.sel(time=...)` puede dejar la dimensión `time` con largo 1 según
    # cómo xarray resuelva el partial-string indexing; nos quedamos siempre
    # con la primera lámina (lat, lon) para que el resto sea 2-D.
    if sst_arr.ndim == 3:
        sst_arr = sst_arr[0]
        chl_arr = chl_arr[0]

    mask = ~(np.isnan(sst_arr) | np.isnan(chl_arr))
    if not mask.any():
        return None

    lat_grid = ds_day["latitude"].values
    lon_grid = ds_day["longitude"].values
    lat_idx, lon_idx = np.where(mask)
    lat_valid = lat_grid[lat_idx]
    lon_valid = lon_grid[lon_idx]
    sst_valid = sst_arr[mask]
    chl_valid = chl_arr[mask]

    tree = cKDTree(project_xy(lat_valid, lon_valid))
    return tree, lat_valid, lon_valid, sst_valid, chl_valid


def enrich_one_day(
    ships_day: pd.DataFrame, ds_day: xr.Dataset
) -> dict[str, np.ndarray] | None:
    """Para todos los lances de un mismo día, devuelve los valores de las
    columnas nuevas alineados al índice de `ships_day`. Devuelve None si
    no hay celdas válidas ese día.
    """
    result = build_day_tree(ds_day)
    if result is None:
        return None
    tree, lat_valid, lon_valid, sst_valid, chl_valid = result

    ship_xy = project_xy(
        ships_day["LATITUD_DD"].to_numpy(),
        ships_day["LONGITUD_DD"].to_numpy(),
    )
    distances, idx = tree.query(ship_xy)

    return {
        "LAT_GRILLA": lat_valid[idx],
        "LON_GRILLA": lon_valid[idx],
        "DISTANCIA_KM_GRILLA": distances * DEG_TO_KM,
        "analysed_sst_celsius": sst_valid[idx],
        "chl_mg_m3": chl_valid[idx],
    }


def main() -> None:
    ds = load_grid_dataset()
    df = load_ships(INPUT_CSV)

    for col in NEW_COLUMNS:
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

    # Pre-calcular las fechas únicas presentes en el NetCDF para evitar
    # KeyError ruidoso cuando un lance cae justo en un día que el dataset
    # no cubre (gaps esporádicos, redownloads parciales, etc.).
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
    print(
        f"Filas totales:               {total:,}\n"
        f"Filas enriquecidas:          {n_enriquecidas:,}\n"
        f"Filas sin coordenada:        {n_sin_coord:,}\n"
        f"Filas sin fecha UTC:         {n_sin_fecha:,}\n"
        f"Filas fuera de bbox:         {n_fuera_bbox:,}\n"
        f"Filas fuera de rango fecha:  {n_fuera_rango:,}\n"
        f"Filas sin día en grilla:     {n_sin_fecha_grilla:,}\n"
        f"Filas sin celdas válidas:    {n_sin_celdas_validas:,}\n"
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
