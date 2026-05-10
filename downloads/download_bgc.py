"""
Descarga datos biogeoquímicos de Copernicus Marine para la costa de
Atacama (lat -29 a -25, lon -72 a -70) entre 2017 y 2022 a partir del
producto GLOBAL_MULTIYEAR_BGC_001_029. De ese producto extrae:

    - o2_min_0_200m : oxígeno disuelto mínimo entre 0 y 200 m (mmol/m³),
                      proxy del techo de la zona de mínima oxigenación
                      (OMZ) que limita la distribución de jurel.
    - zooc          : biomasa de zooplancton en superficie (mmol/m³).
    - phyc          : biomasa de fitoplancton en superficie (mmol/m³).
    - nppv          : producción primaria neta vertical en superficie
                      (mg C/m³/día).

Atención: el producto BGC viene a 0.25° (≈25 km), bastante más grueso
que SST/CHL. El regrillado bilineal a 1/24° suaviza inevitablemente la
señal — no introduce información nueva, sólo la pone en la grilla
compartida para que el merge downstream sea trivial.

Las credenciales se leen exclusivamente de las variables de entorno
COPERNICUS_USERNAME y COPERNICUS_PASSWORD (cargadas desde .env por Compose).
"""

import os
import sys
import traceback

import copernicusmarine
import xarray as xr

from utils.cmems_common import print_summary, read_credentials, regrid_to_target


# Producto: GLOBAL_MULTIYEAR_BGC_001_029 (Mercator BIORYS reanalysis,
# diario, 0.25°). copernicusmarine.subset() requiere el ID de DATASET.
# Si Copernicus lo renombra, ver README → "Solución de problemas".
DATASET_ID = "cmems_mod_glo_bgc_my_0.25deg_P1D-m"
VARIABLES = ["o2", "zooc", "phyc", "nppv"]

START_DATE = "2017-01-01"
END_DATE = "2022-12-31"

LAT_MIN, LAT_MAX = -29.0, -25.0
LON_MIN, LON_MAX = -72.0, -70.0

# Rango vertical: 0–200 m cubre la columna de agua donde se encuentra
# el techo de la OMZ frente a Atacama. Para zooc/phyc/nppv tomamos sólo
# el nivel superficial; para o2 reducimos a su mínimo en la columna.
DEPTH_MIN = 0.0
DEPTH_MAX = 200.0
DEPTH_SURFACE = 0.0

OUTPUT_DIR = "/app/data"
NC_FILENAME = "bgc_atacama_2017_2022.nc"
CSV_FILENAME = "bgc_atacama_2017_2022.csv"

OUTPUT_VARIABLES = {
    "o2_min_0_200m": "mmol/m³",
    "zooc": "mmol/m³",
    "phyc": "mmol/m³",
    "nppv": "mg C/m³/día",
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


def _surface(da: xr.DataArray) -> xr.DataArray:
    """Selecciona el nivel superficial y descarta la coord escalar
    `depth` resultante."""
    selected = da.sel(depth=DEPTH_SURFACE, method="nearest")
    if "depth" in selected.coords:
        selected = selected.drop_vars("depth")
    return selected


def regrid_and_export(nc_path: str) -> str:
    """Reduce el rango vertical a campos 2-D (mínimo 0–200 m para O₂,
    superficie para el resto), regrilla a la grilla destino común,
    reescribe el NetCDF y exporta el CSV."""
    csv_path = os.path.join(OUTPUT_DIR, CSV_FILENAME)
    print(f"Reduciendo profundidades y regrillando {nc_path}...")

    with xr.open_dataset(nc_path) as ds_raw:
        ds = ds_raw.load()

    # Mínimo de O₂ en la columna 0–200 m: proxy del techo de la OMZ.
    o2_min = ds["o2"].min(dim="depth", skipna=True)

    # zooc / phyc / nppv en superficie.
    surface_vars = {name: _surface(ds[name]) for name in ("zooc", "phyc", "nppv")}

    ds = ds.drop_vars(["o2", "zooc", "phyc", "nppv"])
    ds = ds.assign(o2_min_0_200m=o2_min, **surface_vars)

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
    username, password = read_credentials()
    nc_path = download(username, password)
    csv_path = regrid_and_export(nc_path)
    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
