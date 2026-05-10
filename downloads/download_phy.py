"""
Descarga datos físicos de Copernicus Marine para la costa de Atacama
(lat -29 a -25, lon -72 a -70) entre 2017 y 2022 a partir del producto
GLOBAL_MULTIYEAR_PHY_001_030. De ese producto extrae:

    - mlotst       : Mixed Layer Depth (m), superficial.
    - so_0m        : salinidad practica en superficie (PSU).
    - thetao_400m  : temperatura potencial a ~400 m de profundidad (°C).

Las dos últimas se obtienen seleccionando el nivel de profundidad más
cercano dentro del subconjunto descargado. El resultado se regrilla a la
grilla destino común (ver utils/cmems_common.py) y se exporta como NetCDF
y CSV en /app/data.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback

import copernicusmarine
import xarray as xr

from utils.cmems_common import print_summary, read_credentials, regrid_to_target


# Producto: GLOBAL_MULTIYEAR_PHY_001_030 (Mercator GLORYS12 reanalysis,
# diario, 1/12°). copernicusmarine.subset() requiere el ID de DATASET, no
# el de producto. Si Copernicus lo renombra, ver el README (sección
# "Solución de problemas") para descubrir el nuevo ID.
DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
VARIABLES = ["mlotst", "so", "thetao"]

START_DATE = "2017-01-01"
END_DATE = "2022-12-31"

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
NC_FILENAME = "phy_atacama_2017_2022.nc"
CSV_FILENAME = "phy_atacama_2017_2022.csv"

# Columnas finales del CSV (también las que se vuelcan al NetCDF
# regrillado en disco) y sus unidades para el resumen.
OUTPUT_VARIABLES = {
    "mlotst": "m",
    "so_0m": "PSU",
    "thetao_400m": "°C",
}


def download(username: str, password: str) -> str:
    """Descarga el subconjunto NetCDF y devuelve la ruta del archivo."""
    print(
        f"Descargando {VARIABLES} de {DATASET_ID}\n"
        f"  Rango temporal:  {START_DATE} a {END_DATE}\n"
        f"  Latitud:         {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:        {LON_MIN} a {LON_MAX}\n"
        f"  Profundidad:     {DEPTH_MIN} m a {DEPTH_MAX} m"
    )
    try:
        copernicusmarine.subset(
            dataset_id=DATASET_ID,
            variables=VARIABLES,
            start_datetime=START_DATE,
            end_datetime=END_DATE,
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            minimum_depth=DEPTH_MIN,
            maximum_depth=DEPTH_MAX,
            output_directory=OUTPUT_DIR,
            output_filename=NC_FILENAME,
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

    return os.path.join(OUTPUT_DIR, NC_FILENAME)


def _select_level(da: xr.DataArray, depth: float) -> xr.DataArray:
    """Selecciona el nivel de profundidad más cercano y descarta la coord
    escalar `depth` resultante para que todas las variables compartan
    coordenadas (time, latitude, longitude) sin ambigüedad."""
    selected = da.sel(depth=depth, method="nearest")
    if "depth" in selected.coords:
        selected = selected.drop_vars("depth")
    return selected


def regrid_and_export(nc_path: str) -> str:
    """Reduce las variables con dimensión de profundidad a campos 2-D,
    regrilla a la grilla destino común, reescribe el NetCDF y exporta
    el CSV con las columnas finales."""
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
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
    username, password = read_credentials()
    nc_path = download(username, password)
    csv_path = regrid_and_export(nc_path)
    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
