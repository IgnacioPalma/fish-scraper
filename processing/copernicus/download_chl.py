"""
Descarga datos de Chlorophyll-a (CHL) de Copernicus Marine para la costa
de Atacama (lat -29 a -25, lon -72 a -70), los regrilla a la grilla destino
común (ver processing/utils/cmems_common.py) y los exporta como NetCDF y CSV en
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
    print_summary,
    read_credentials,
    regrid_to_target,
)
from processing.utils.date_ranges import END_DATE as GLOBAL_END
from processing.utils.date_ranges import START_DATE as GLOBAL_START


# Producto: OCEANCOLOUR_GLO_BGC_L4_MY_009_104 (Multi-Year reprocessed, L4 daily,
# multi-sensor, gap-filled, 4 km). copernicusmarine.subset() requiere el ID de
# DATASET, no el de producto. El segmento "gapfree-" en el nombre indica la
# versión rellenada (sin huecos por nubes). Si Copernicus lo renombra, ver el
# README (sección "Solución de problemas") para descubrir el nuevo ID.
DATASET_ID = "cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D"
VARIABLE = "CHL"

# Disponibilidad del producto en el catálogo Copernicus (a 2026-05-12).
# Si el DATASET_ID `_my_` (reanálisis) no llega hasta PRODUCT_END_DATE,
# Copernicus suele exponer un dataset `_myint_` (interim) hermano que
# extiende la cobertura — ver README "Solución de problemas".
PRODUCT_START_DATE = date(1997, 9, 1)
PRODUCT_END_DATE = date(2026, 5, 4)

OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "copernicus")
FILENAME_BASE = "chl_atacama"


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
    y exporta el CSV con la clorofila en mg/m³."""
    print(f"Regrillando {nc_path} a la grilla destino común...")

    with xr.open_dataset(nc_path) as ds:
        ds_regridded = regrid_to_target(ds).load()

    # Reescribir el NetCDF ya regrillado para que SST y CHL compartan grilla
    ds_regridded.to_netcdf(nc_path)

    print(f"Convirtiendo {nc_path} a CSV...")
    df = ds_regridded[VARIABLE].to_dataframe().reset_index()

    # CHL ya viene en mg/m³, no hay conversión de unidades; solo renombrar para claridad
    df = df.rename(columns={VARIABLE: "chl_mg_m3"})

    # Quedarse con las columnas pedidas y descartar tierra/nubes (NaN)
    df = df[["time", "latitude", "longitude", "chl_mg_m3"]].dropna(
        subset=["chl_mg_m3"]
    )
    df.to_csv(csv_path, index=False)

    print_summary(df, "chl_mg_m3", "mg/m³")
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
