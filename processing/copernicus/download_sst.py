"""
Descarga datos de Sea Surface Temperature (SST) de Copernicus Marine para la
costa de Atacama (lat -29 a -25, lon -72 a -70), los regrilla a la grilla
destino común (ver processing/utils/cmems_common.py) y los exporta como NetCDF y CSV en
`data/copernicus/` (relativo a la raíz del proyecto).

El rango temporal viene del rango global del proyecto (processing/utils/date_ranges.py),
intersectado con la disponibilidad del producto Copernicus declarada acá
abajo (PRODUCT_START_DATE / PRODUCT_END_DATE). Si la intersección queda
vacía, el script lo informa y termina sin descargar.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env mediante python-dotenv).
"""

import os
import sys
import traceback
from datetime import date
from pathlib import Path

import copernicusmarine
import xarray as xr

from processing.utils.cmems_common import (
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    TIME_CHUNK,
    print_summary_da,
    read_credentials,
    regrid_and_write_netcdf,
    stream_dataset_to_csv,
)
from processing.utils.date_ranges import END_DATE as GLOBAL_END
from processing.utils.date_ranges import START_DATE as GLOBAL_START

# El usuario solicitó originalmente el ID de PRODUCTO
# "SST_GLO_SST_L4_REP_OBSERVATIONS_010_011", pero copernicusmarine.subset()
# requiere un ID de DATASET dentro de ese producto. Usamos el dataset L4
# reprocesado diario estándar. Si Copernicus lo renombra, ver el README
# (sección "Solución de problemas") para descubrir el nuevo ID.
DATASET_ID = "METOFFICE-GLO-SST-L4-REP-OBS-SST"
VARIABLE = "analysed_sst"

# Disponibilidad del producto en el catálogo Copernicus (a 2026-05-12).
# Si el DATASET_ID `_my_` (reanálisis) no llega hasta PRODUCT_END_DATE,
# Copernicus suele exponer un dataset `_myint_` (interim) hermano que
# extiende la cobertura — ver README "Solución de problemas".
PRODUCT_START_DATE = date(1981, 10, 1)
PRODUCT_END_DATE = date(2025, 12, 18)

OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "copernicus")
FILENAME_BASE = "sst_atacama"


def download(
    username: str,
    password: str,
    start: date,
    end: date,
    nc_path: str,
) -> str:
    """Descarga el subconjunto NetCDF y devuelve la ruta del archivo."""
    print(
        f"Descargando {VARIABLE} de {DATASET_ID}\n"
        f"  Rango global solicitado:  {GLOBAL_START} a {GLOBAL_END}\n"
        f"  Disponibilidad producto:  {PRODUCT_START_DATE} a {PRODUCT_END_DATE}\n"
        f"  Rango efectivo:           {start} a {end}\n"
        f"  Latitud:                  {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:                 {LON_MIN} a {LON_MAX}"
    )
    try:
        copernicusmarine.subset(
            dataset_id=DATASET_ID,
            variables=[VARIABLE],
            start_datetime=start.isoformat(),
            end_datetime=end.isoformat(),
            minimum_latitude=LAT_MIN,
            maximum_latitude=LAT_MAX,
            minimum_longitude=LON_MIN,
            maximum_longitude=LON_MAX,
            output_directory=os.path.dirname(nc_path),
            output_filename=os.path.basename(nc_path),
            username=username,
            password=password,
            overwrite=True,
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


def regrid_and_export(nc_path: str, csv_path: str) -> str:
    """Regrilla el NetCDF a la grilla destino común, lo reescribe en disco
    y exporta el CSV con la SST en grados Celsius. Todo en streaming por
    bloques de tiempo (dask) para no materializar el cubo completo: con
    bboxes grandes (p. ej. REGION=chile) el interp + export de una sola vez
    agota la RAM del runner de CI."""
    print(f"Regrillando {nc_path} a la grilla destino común (streaming)...")

    with xr.open_dataset(nc_path, chunks={"time": TIME_CHUNK}) as ds:
        regrid_and_write_netcdf(ds[[VARIABLE]], nc_path)

    print(f"Convirtiendo {nc_path} a CSV (streaming por bloques de tiempo)...")
    # analysed_sst llega en Kelvin -> convertir a Celsius. El CSV se escribe
    # por bloques de tiempo (stream_dataset_to_csv) para no expandir el cubo
    # completo a DataFrame de una sola vez.
    with xr.open_dataset(nc_path, chunks={"time": TIME_CHUNK}) as ds_rg:
        stream_dataset_to_csv(
            ds_rg[[VARIABLE]],
            ["analysed_sst_celsius"],
            csv_path,
            transform=lambda df: df.assign(analysed_sst_celsius=df[VARIABLE] - 273.15),
            time_chunk=TIME_CHUNK,
        )
        print_summary_da(ds_rg[VARIABLE] - 273.15, "analysed_sst_celsius", "°C")
    return csv_path


def main(force: bool = False) -> None:
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

    # Skip-if-exists: si el .nc y el .csv ya están (p. ej. traídos de R2), no
    # se vuelve a descargar. Con --force se ignoran y se rebajan.
    if not force and os.path.exists(nc_path) and os.path.exists(csv_path):
        print(f"(ya existen; se omite la descarga)\n  {nc_path}\n  {csv_path}")
        print("  Usá --force para volver a descargar.")
        return

    username, password = read_credentials()
    download(username, password, effective_start, effective_end, nc_path)
    regrid_and_export(nc_path, csv_path)
    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    import argparse

    _parser = argparse.ArgumentParser(description=__doc__)
    _parser.add_argument(
        "--force",
        action="store_true",
        help="Vuelve a descargar aunque el .nc/.csv ya existan.",
    )
    main(force=_parser.parse_args().force)
