"""
Descarga datos físicos de Copernicus Marine para la costa de Atacama
(lat -29 a -25, lon -72 a -70) a partir del producto
GLOBAL_MULTIYEAR_PHY_001_030. De ese producto extrae:

    - mlotst       : Mixed Layer Depth (m), superficial.
    - so_0m        : salinidad practica en superficie (PSU).
    - thetao_400m  : temperatura potencial a ~400 m de profundidad (°C).

Las dos últimas se obtienen seleccionando el nivel de profundidad más
cercano dentro del subconjunto descargado. El resultado se regrilla a la
grilla destino común (ver processing/utils/cmems_common.py) y se exporta como NetCDF
y CSV en /app/data.

El rango temporal viene del rango global del proyecto (processing/utils/date_ranges.py),
intersectado con la disponibilidad del producto Copernicus declarada acá
abajo (PRODUCT_START_DATE / PRODUCT_END_DATE). Si la intersección queda
vacía, el script lo informa y termina sin descargar.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback
from datetime import date

import copernicusmarine
import xarray as xr

from processing.utils.cmems_common import print_summary, read_credentials, regrid_to_target
from processing.utils.date_ranges import END_DATE as GLOBAL_END
from processing.utils.date_ranges import START_DATE as GLOBAL_START


# Producto: GLOBAL_MULTIYEAR_PHY_001_030 (Mercator GLORYS12 reanalysis,
# diario, 1/12°). copernicusmarine.subset() requiere el ID de DATASET, no
# el de producto. Si Copernicus lo renombra, ver el README (sección
# "Solución de problemas") para descubrir el nuevo ID.
DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARIABLES = ["mlotst", "so", "thetao"]

# Disponibilidad del producto en el catálogo Copernicus (a 2026-05-12).
# Si el DATASET_ID `_my_` (reanálisis) no llega hasta PRODUCT_END_DATE,
# Copernicus suele exponer un dataset `_myint_` (interim) hermano que
# extiende la cobertura — ver README "Solución de problemas".
PRODUCT_START_DATE = date(1993, 1, 1)
PRODUCT_END_DATE = date(2026, 4, 28)

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

# Rango vertical del subset: necesitamos superficie (so, thetao en 0 m,
# y mlotst que es 2-D) y un nivel cercano a 400 m (thetao_400m). Pedir
# todo el rango 0–400 m en una sola llamada y reducir en post-proceso
# es más simple que hacer dos descargas separadas.
DEPTH_MIN = 0.0
DEPTH_MAX = 400.0

# Profundidades objetivo para la reducción a campos 2-D.
DEPTH_SURFACE = 0.0
DEPTH_DEEP = 400.0

OUTPUT_DIR = "/app/data"
FILENAME_BASE = "phy_atacama"

# Columnas finales del CSV (también las que se vuelcan al NetCDF
# regrillado en disco) y sus unidades para el resumen.
OUTPUT_VARIABLES = {
    "mlotst": "m",
    "so_0m": "PSU",
    "thetao_400m": "°C",
}


def download(
    username: str,
    password: str,
    start: date,
    end: date,
    nc_path: str,
) -> str:
    """Descarga el subconjunto NetCDF y devuelve la ruta del archivo."""
    print(
        f"Descargando {VARIABLES} de {DATASET_ID}\n"
        f"  Rango global solicitado:  {GLOBAL_START} a {GLOBAL_END}\n"
        f"  Disponibilidad producto:  {PRODUCT_START_DATE} a {PRODUCT_END_DATE}\n"
        f"  Rango efectivo:           {start} a {end}\n"
        f"  Latitud:                  {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:                 {LON_MIN} a {LON_MAX}\n"
        f"  Profundidad:              {DEPTH_MIN} m a {DEPTH_MAX} m"
    )
    try:
        copernicusmarine.subset(
            dataset_id=DATASET_ID,
            variables=VARIABLES,
            start_datetime=start.isoformat(),
            end_datetime=end.isoformat(),
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            minimum_depth=DEPTH_MIN,
            maximum_depth=DEPTH_MAX,
            output_directory=os.path.dirname(nc_path),
            output_filename=os.path.basename(nc_path),
            username=username,
            password=password,
        )
    except Exception as exc:
        print(
            "ERROR: la descarga desde Copernicus Marine falló.\n"
            f"       Detalle: {exc}\n"
            "       Revisa: credenciales, ID de dataset, conexión a internet.",
            file=sys.stderr,
        )
        traceback.print_exc()
        sys.exit(2)

    return nc_path


def _select_level(da: xr.DataArray, depth: float) -> xr.DataArray:
    """Selecciona el nivel de profundidad más cercano y descarta la coord
    escalar `depth` resultante para que todas las variables compartan
    coordenadas (time, latitude, longitude) sin ambigüedad."""
    selected = da.sel(depth=depth, method="nearest")
    if "depth" in selected.coords:
        selected = selected.drop_vars("depth")
    return selected


def regrid_and_export(nc_path: str, csv_path: str) -> str:
    """Reduce las variables con dimensión de profundidad a campos 2-D,
    regrilla a la grilla destino común, reescribe el NetCDF y exporta
    el CSV con las columnas finales."""
    print(f"Reduciendo profundidades y regrillando {nc_path}...")

    with xr.open_dataset(nc_path) as ds_raw:
        ds = ds_raw.load()

    # so y thetao tienen dimensión de profundidad; mlotst no.
    ds = ds.assign(
        so_0m=_select_level(ds["so"], DEPTH_SURFACE),
        thetao_400m=_select_level(ds["thetao"], DEPTH_DEEP),
    ).drop_vars(["so", "thetao"])

    # Tras el sel/drop anterior ya no hay variables que usen la dim
    # `depth`, pero la coord aún vive a nivel de Dataset con N niveles
    # (los del subset 0–400 m). La eliminamos para que `to_netcdf` y
    # `to_dataframe` queden limpios y la dim `depth` no aparezca en
    # los archivos de salida.
    if "depth" in ds.coords:
        ds = ds.drop_vars("depth")

    ds_regridded = regrid_to_target(ds).load()

    # Reescribir el NetCDF ya regrillado para que Jupyter y los cruces
    # downstream vean exactamente la grilla unificada.
    ds_regridded.to_netcdf(nc_path)

    print(f"Convirtiendo {nc_path} a CSV...")
    df = ds_regridded[list(OUTPUT_VARIABLES)].to_dataframe().reset_index()

    # Descartar tierra/celdas sin datos: una fila se conserva si AL MENOS
    # una de las variables físicas trae valor (las NaN coastal de mlotst
    # no deben botar la fila si la salinidad sí está disponible, etc.).
    df = df[["time", "latitude", "longitude", *OUTPUT_VARIABLES]].dropna(
        subset=list(OUTPUT_VARIABLES), how="all"
    )
    df.to_csv(csv_path, index=False)

    for col, unit in OUTPUT_VARIABLES.items():
        print_summary(df.dropna(subset=[col]), col, unit)
    return csv_path


def main() -> None:
    effective_start = max(GLOBAL_START, PRODUCT_START_DATE)
    effective_end = min(GLOBAL_END, PRODUCT_END_DATE)

    if effective_start > effective_end:
        print(
            f"Rango global {GLOBAL_START}–{GLOBAL_END} está fuera de la "
            f"disponibilidad del producto ({PRODUCT_START_DATE}–"
            f"{PRODUCT_END_DATE}). No hay nada que descargar para "
            f"{DATASET_ID}.",
            file=sys.stderr,
        )
        sys.exit(0)

    year_tag = (
        f"{effective_start.year}"
        if effective_start.year == effective_end.year
        else f"{effective_start.year}_{effective_end.year}"
    )
    nc_path = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{year_tag}.nc")
    csv_path = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{year_tag}.csv")

    username, password = read_credentials()
    download(username, password, effective_start, effective_end, nc_path)
    regrid_and_export(nc_path, csv_path)
    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
