"""
Descarga datos altimétricos diarios de Copernicus Marine para la costa
de Atacama (lat -29 a -25, lon -72 a -70) a partir del producto
SEALEVEL_GLO_PHY_L4_MY_008_047. Variables:

    - sla   : anomalía del nivel del mar (m).
    - adt   : topografía dinámica absoluta (m).
    - ugos  : velocidad geostrófica zonal en superficie (m/s).
    - vgos  : velocidad geostrófica meridional en superficie (m/s).

La altimetría L4 multi-misión llega a 0.125° (≈12 km). El regrillado
bilineal a 1/24° interpola hacia una grilla más fina; deja todas las
capas en la grilla compartida con SST/CHL para que el merge
downstream sea trivial.

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

from processing.utils.cmems_common import print_summary, read_credentials, regrid_to_target
from processing.utils.date_ranges import END_DATE as GLOBAL_END
from processing.utils.date_ranges import START_DATE as GLOBAL_START


# Producto: SEALEVEL_GLO_PHY_L4_MY_008_047 (DUACS multi-misión, diario,
# 0.125°). copernicusmarine.subset() requiere el ID de DATASET. Si
# Copernicus lo renombra, ver README → "Solución de problemas".
DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D"
VARIABLES = ["sla", "adt", "ugos", "vgos"]

# Disponibilidad del producto en el catálogo Copernicus (a 2026-05-12).
# Si el DATASET_ID `_my_` (reanálisis) no llega hasta PRODUCT_END_DATE,
# Copernicus suele exponer un dataset `_myint_` (interim) hermano que
# extiende la cobertura — ver README "Solución de problemas".
PRODUCT_START_DATE = date(1993, 1, 1)
PRODUCT_END_DATE = date(2025, 10, 18)

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "copernicus")
FILENAME_BASE = "sla_atacama"

OUTPUT_VARIABLES = {
    "sla": "m",
    "adt": "m",
    "ugos": "m/s",
    "vgos": "m/s",
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
        f"  Longitud:                 {LON_MIN} a {LON_MAX}"
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
    """Regrilla el NetCDF a la grilla destino común, lo reescribe en
    disco y exporta el CSV con las cuatro variables altimétricas."""
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
