"""
Descarga datos altimétricos diarios de Copernicus Marine para la costa
de Atacama (lat -29 a -25, lon -72 a -70) entre 2017 y 2022 a partir
del producto SEALEVEL_GLO_PHY_L4_MY_008_047. Variables:

    - sla   : anomalía del nivel del mar (m).
    - adt   : topografía dinámica absoluta (m).
    - ugos  : velocidad geostrófica zonal en superficie (m/s).
    - vgos  : velocidad geostrófica meridional en superficie (m/s).

La altimetría L4 multi-misión llega a 0.125° (≈12 km). El regrillado
bilineal a 1/24° interpola hacia una grilla más fina; deja todas las
capas en la grilla compartida con SST/CHL para que el merge
downstream sea trivial.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback

import copernicusmarine
import xarray as xr

from utils.cmems_common import print_summary, read_credentials, regrid_to_target


# Producto: SEALEVEL_GLO_PHY_L4_MY_008_047 (DUACS multi-misión, diario,
# 0.125°). copernicusmarine.subset() requiere el ID de DATASET. Si
# Copernicus lo renombra, ver README → "Solución de problemas".
DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D"
VARIABLES = ["sla", "adt", "ugos", "vgos"]

START_DATE = "2017-01-01"
END_DATE = "2022-12-31"

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

OUTPUT_DIR = "/app/data"
NC_FILENAME = "sla_atacama_2017_2022.nc"
CSV_FILENAME = "sla_atacama_2017_2022.csv"

OUTPUT_VARIABLES = {
    "sla": "m",
    "adt": "m",
    "ugos": "m/s",
    "vgos": "m/s",
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
    """Regrilla el NetCDF a la grilla destino común, lo reescribe en
    disco y exporta el CSV con las cuatro variables altimétricas."""
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    print(f"Regrillando {nc_path} a la grilla destino común...")

    with xr.open_dataset(nc_path) as ds:
        ds_regridded = regrid_to_target(ds[list(OUTPUT_VARIABLES)]).load()

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
