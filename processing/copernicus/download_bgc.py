"""
Descarga datos biogeoquímicos de Copernicus Marine para la costa de
Atacama (lat -29 a -25, lon -72 a -70) a partir del producto
GLOBAL_MULTIYEAR_BGC_001_029. De ese producto extrae:

    - o2_min_0_200m : oxígeno disuelto mínimo entre 0 y 200 m (mmol/m³),
                      proxy del techo de la zona de mínima oxigenación
                      (OMZ) que limita la distribución de jurel.
    - nppv          : producción primaria neta vertical en superficie
                      (mg C/m³/día).

Sobre las variables que no están en este producto:
    El reanálisis BGC global a 0.25° expone únicamente {chl, no3, nppv,
    o2, po4, si}. NO incluye `phyc` (fitoplancton) ni `zooc`
    (zooplancton) para nuestro período. Si en el futuro necesitamos
    biomasa de plancton, hay que pasarse a un producto distinto (p. ej.
    el regional IBI o un near-real-time) o a un modelo distinto. Por
    ahora, `nppv` cumple un rol parecido como índice de productividad —
    la literatura de jurel pondera más el techo de la OMZ (vía
    `o2_min_0_200m`) que el plancton mismo.

Atención: el producto BGC viene a 0.25° (≈25 km), bastante más grueso
que SST/CHL. El regrillado bilineal a 1/24° suaviza inevitablemente la
señal — no introduce información nueva, sólo la pone en la grilla
compartida para que el merge downstream sea trivial.

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


# Producto: GLOBAL_MULTIYEAR_BGC_001_029 (Mercator BIORYS reanalysis,
# diario, 0.25°). copernicusmarine.subset() requiere el ID de DATASET.
# Si Copernicus lo renombra, ver README → "Solución de problemas".
DATASET_ID = "cmems_mod_glo_bgc_my_0.25deg_P1D-m"
VARIABLES = ["o2", "nppv"]

# Disponibilidad del producto en el catálogo Copernicus (a 2026-05-12).
# Si el DATASET_ID `_my_` (reanálisis) no llega hasta PRODUCT_END_DATE,
# Copernicus suele exponer un dataset `_myint_` (interim) hermano que
# extiende la cobertura — ver README "Solución de problemas".
PRODUCT_START_DATE = date(1993, 1, 1)
PRODUCT_END_DATE = date(2026, 2, 28)

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

# Rango vertical: 0–200 m cubre la columna de agua donde se encuentra
# el techo de la OMZ frente a Atacama. Para nppv tomamos sólo el nivel
# superficial; para o2 reducimos a su mínimo en la columna.
DEPTH_MIN = 0.0
DEPTH_MAX = 200.0
DEPTH_SURFACE = 0.0

OUTPUT_DIR = "/app/data/copernicus"
FILENAME_BASE = "bgc_atacama"

OUTPUT_VARIABLES = {
    "o2_min_0_200m": "mmol/m³",
    "nppv": "mg C/m³/día",
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


def _surface(da: xr.DataArray) -> xr.DataArray:
    """Selecciona el nivel superficial y descarta la coord escalar
    `depth` resultante."""
    selected = da.sel(depth=DEPTH_SURFACE, method="nearest")
    if "depth" in selected.coords:
        selected = selected.drop_vars("depth")
    return selected


def regrid_and_export(nc_path: str, csv_path: str) -> str:
    """Reduce el rango vertical a campos 2-D (mínimo 0–200 m para O₂,
    superficie para nppv), regrilla a la grilla destino común,
    reescribe el NetCDF y exporta el CSV."""
    print(f"Reduciendo profundidades y regrillando {nc_path}...")

    with xr.open_dataset(nc_path) as ds_raw:
        ds = ds_raw.load()

    # Mínimo de O₂ en la columna 0–200 m: proxy del techo de la OMZ.
    o2_min = ds["o2"].min(dim="depth", skipna=True)
    nppv_surface = _surface(ds["nppv"])

    ds = ds.drop_vars(["o2", "nppv"])
    ds = ds.assign(o2_min_0_200m=o2_min, nppv=nppv_surface)

    # Tras el min/sel anterior ya no hay variables que usen la dim
    # `depth`, pero la coord aún vive a nivel de Dataset con los
    # niveles del subset (0–200 m). La eliminamos para que `to_netcdf`
    # y `to_dataframe` queden limpios y la dim `depth` no aparezca en
    # los archivos de salida.
    if "depth" in ds.coords:
        ds = ds.drop_vars("depth")

    ds_regridded = regrid_to_target(ds).load()
    ds_regridded.to_netcdf(nc_path)

    print(f"Convirtiendo {nc_path} a CSV...")
    df = ds_regridded[list(OUTPUT_VARIABLES)].to_dataframe().reset_index()
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
