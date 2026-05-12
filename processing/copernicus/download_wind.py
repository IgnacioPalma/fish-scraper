"""
Descarga datos de viento de superficie de Copernicus Marine para la
costa de Atacama (lat -29 a -25, lon -72 a -70) entre 2017 y 2022 a
partir del producto WIND_GLO_PHY_L4_MY_012_006. Variables:

    - eastward_wind   : componente zonal del viento a 10 m (m/s).
    - northward_wind  : componente meridional del viento a 10 m (m/s).

El producto base es horario; aquí lo agregamos a media diaria antes de
regrillar para mantener la cadencia diaria del resto del pipeline (SST,
CHL, PHY, BGC, SLA). Si Copernicus llegara a publicar un dataset L4
ya pre-agregado a paso diario (`_P1D`), conviene cambiar `DATASET_ID`
y eliminar el resample en `regrid_and_export` — guardar 24× menos
NetCDF en disco.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback

import copernicusmarine
import xarray as xr

from utils.cmems_common import print_summary, read_credentials, regrid_to_target


# Producto: WIND_GLO_PHY_L4_MY_012_006 (Multi-Year reprocessed, L4
# horario, 0.125°). copernicusmarine.subset() requiere el ID de
# DATASET. Si Copernicus lo renombra, ver README → "Solución de
# problemas".
DATASET_ID = "cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H"
VARIABLES = ["eastward_wind", "northward_wind"]

START_DATE = "2017-01-01"
END_DATE = "2022-12-31"

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

OUTPUT_DIR = "/app/data"
NC_FILENAME = "wind_atacama_2017_2022.nc"
CSV_FILENAME = "wind_atacama_2017_2022.csv"

OUTPUT_VARIABLES = {
    "eastward_wind": "m/s",
    "northward_wind": "m/s",
}


def download(username: str, password: str) -> str:
    """Descarga el subconjunto NetCDF y devuelve la ruta del archivo."""
    print(
        f"Descargando {VARIABLES} de {DATASET_ID}\n"
        f"  Rango temporal:  {START_DATE} a {END_DATE}\n"
        f"  Latitud:         {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:        {LON_MIN} a {LON_MAX}"
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


def regrid_and_export(nc_path: str) -> str:
    """Agrega el viento horario a media diaria, regrilla a la grilla
    destino común, reescribe el NetCDF y exporta el CSV con las dos
    componentes."""
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    print(f"Agregando a media diaria y regrillando {nc_path}...")

    with xr.open_dataset(nc_path) as ds_raw:
        ds = ds_raw.load()

    # Promedio diario: imprescindible para alinear con el resto del
    # pipeline (SST/CHL/PHY/BGC/SLA son P1D). Si el dataset ya viene
    # diario el resample es un no-op.
    ds_daily = ds[list(OUTPUT_VARIABLES)].resample(time="1D").mean()

    ds_regridded = regrid_to_target(ds_daily).load()
    ds_regridded.to_netcdf(nc_path)

    print(f"Convirtiendo {nc_path} a CSV...")
    df = ds_regridded.to_dataframe().reset_index()
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
