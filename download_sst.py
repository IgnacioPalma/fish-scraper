"""
Descarga datos de Sea Surface Temperature (SST) de Copernicus Marine para la
costa de Atacama (lat -29 a -25, lon -72 a -70) entre 2017 y 2022, los
regrilla a la grilla destino común (ver cmems_common.py) y los exporta
como NetCDF y CSV en /app/data.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback

import copernicusmarine
import xarray as xr

from cmems_common import print_summary, read_credentials, regrid_to_target


# El usuario solicitó originalmente el ID de PRODUCTO
# "SST_GLO_SST_L4_REP_OBSERVATIONS_010_011", pero copernicusmarine.subset()
# requiere un ID de DATASET dentro de ese producto. Usamos el dataset L4
# reprocesado diario estándar. Si Copernicus lo renombra, ver el README
# (sección "Solución de problemas") para descubrir el nuevo ID.
DATASET_ID = "METOFFICE-GLO-SST-L4-REP-OBS-SST"
VARIABLE = "analysed_sst"

START_DATE = "2017-01-01"
END_DATE = "2022-12-31"

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

OUTPUT_DIR = "/app/data"
NC_FILENAME = "sst_atacama_2017_2022.nc"
CSV_FILENAME = "sst_atacama_2017_2022.csv"


def download(username: str, password: str) -> str:
    """Descarga el subconjunto NetCDF y devuelve la ruta del archivo."""
    print(
        f"Descargando {VARIABLE} de {DATASET_ID}\n"
        f"  Rango temporal:  {START_DATE} a {END_DATE}\n"
        f"  Latitud:         {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:        {LON_MIN} a {LON_MAX}"
    )
    try:
        copernicusmarine.subset(
            dataset_id=DATASET_ID,
            variables=[VARIABLE],
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
    """Regrilla el NetCDF a la grilla destino común, lo reescribe en disco
    y exporta el CSV con la SST en grados Celsius."""
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    print(f"Regrillando {nc_path} a la grilla destino común...")

    with xr.open_dataset(nc_path) as ds:
        ds_regridded = regrid_to_target(ds).load()

    # Reescribir el NetCDF ya regrillado para que Jupyter, etc. vean la grilla unificada
    ds_regridded.to_netcdf(nc_path)

    print(f"Convirtiendo {nc_path} a CSV...")
    df = ds_regridded[VARIABLE].to_dataframe().reset_index()

    # analysed_sst llega en Kelvin -> convertir a Celsius
    df["analysed_sst_celsius"] = df[VARIABLE] - 273.15

    # Quedarse con las columnas pedidas y descartar tierra (NaN sobre continente)
    df = df[["time", "latitude", "longitude", "analysed_sst_celsius"]].dropna(
        subset=["analysed_sst_celsius"]
    )
    df.to_csv(csv_path, index=False)

    print_summary(df, "analysed_sst_celsius", "°C")
    return csv_path


def main() -> None:
    username, password = read_credentials()
    nc_path = download(username, password)
    csv_path = regrid_and_export(nc_path)
    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
