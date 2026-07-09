"""
Descarga el PRONÓSTICO físico de Copernicus Marine para la costa de Atacama
(lat -29 a -25, lon -72 a -70) a partir del producto operacional
GLOBAL_ANALYSISFORECAST_PHY_001_024 (Mercator, análisis + 10 días de
forecast, diario, 1/12°). De ese producto extrae las tres covariables
físicas que alimentan el modelo de jurel, ya con sus nombres finales de
columna:

    sst_c    ← thetao @ superficie (0 m)   temperatura potencial superficial (°C)
    mld_m    ← mlotst (2-D)                 Mixed Layer Depth (m)
    sss_psu  ← so @ superficie (0 m)        salinidad práctica superficial (PSU)

Diferencia con `download_phy.py` (reanálisis `_my_`, histórico):
  - Apunta a los datasets de ANÁLISIS Y PRONÓSTICO (`anfc`), no al reanálisis.
  - El rango temporal NO viene del rango global del proyecto (histórico,
    processing/utils/date_ranges.py), sino de una ventana DINÁMICA hacia
    adelante: desde hoy hasta hoy + FORECAST_DAYS (~10 días, horizonte
    máximo del sistema operacional global).
  - En el sistema operacional las variables están separadas en datasets
    distintos (thetao, so cada una con dimensión de profundidad; mlotst en
    el dataset de campos 2-D), así que se hacen varias llamadas a
    `copernicusmarine.subset()` y se unen con `xr.merge`.

CAVEAT sobre `sst_c`: el modelo se entrenó con SST observada OSTIA L4
(`analysed_sst`); pero para días FUTUROS no existe observación, así que el
pronóstico usa la temperatura superficial del modelo físico (`thetao` @ 0 m).
Misma unidad (°C), fuente algo distinta — es la única opción para predecir
días futuros. Se conserva el nombre de columna `sst_c` para que las entradas
del modelo calcen.

El resultado se regrilla a la grilla destino común (ver
processing/utils/cmems_common.py) y se exporta como NetCDF y CSV en
`data/copernicus/`.

Las credenciales se leen de COPERNICUS_USERNAME / COPERNICUS_PASSWORD
(cargadas desde .env mediante python-dotenv).

Uso:
    uv run python -m processing.copernicus.download_phy_forecast
"""

import os
import sys
import traceback
from datetime import date, timedelta
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


# Horizonte de pronóstico del sistema operacional global (~10 días).
FORECAST_DAYS = 10

# Datasets `anfc` (análisis + forecast) del producto
# GLOBAL_ANALYSISFORECAST_PHY_001_024. copernicusmarine.subset() requiere el
# ID de DATASET, no el de producto. En el sistema operacional cada variable
# vive en su propio dataset; mlotst está en el dataset de campos 2-D. Si
# Copernicus los renombra, ver README ("Solución de problemas").
DATASET_THETAO = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"
DATASET_SO = "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m"
DATASET_2D = "cmems_mod_glo_phy_anfc_0.083deg_P1D-m"

# Sólo necesitamos el nivel superficial de thetao y so. Pedir 0–1 m basta
# para traer la primera capa y reducir el volumen de descarga.
DEPTH_MIN = 0.0
DEPTH_MAX = 1.0
DEPTH_SURFACE = 0.0

OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "copernicus")
FILENAME_BASE = "phy_forecast_atacama"

# Columnas finales del CSV (ya con el nombre que consume el modelo) y unidades.
OUTPUT_VARIABLES = {
    "sst_c": "°C",
    "mld_m": "m",
    "sss_psu": "PSU",
}


def _subset(
    username: str,
    password: str,
    dataset_id: str,
    variables: list[str],
    start: date,
    end: date,
    nc_path: str,
    with_depth: bool,
) -> str:
    """Descarga un subconjunto NetCDF de un dataset y devuelve su ruta.

    `with_depth=False` para datasets 2-D (mlotst): no se pasan los límites de
    profundidad, que harían fallar la petición."""
    print(
        f"Descargando {variables} de {dataset_id}\n"
        f"  Rango efectivo:  {start} a {end}\n"
        f"  Latitud:         {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:        {LON_MIN} a {LON_MAX}"
        + (f"\n  Profundidad:     {DEPTH_MIN} m a {DEPTH_MAX} m" if with_depth else "")
    )
    kwargs = dict(
        dataset_id=dataset_id,
        variables=variables,
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
    if with_depth:
        kwargs["minimum_depth"] = DEPTH_MIN
        kwargs["maximum_depth"] = DEPTH_MAX
    try:
        copernicusmarine.subset(**kwargs)
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


def regrid_and_export(
    thetao_nc: str, so_nc: str, mlotst_nc: str, nc_path: str, csv_path: str
) -> str:
    """Reduce thetao/so a superficie, arma las tres covariables con su nombre
    final, regrilla a la grilla destino común, reescribe el NetCDF y exporta
    el CSV."""
    print("Reduciendo a superficie y regrillando el pronóstico físico...")

    with xr.open_dataset(thetao_nc) as d:
        thetao = _select_level(d["thetao"].load(), DEPTH_SURFACE)
    with xr.open_dataset(so_nc) as d:
        so = _select_level(d["so"].load(), DEPTH_SURFACE)
    with xr.open_dataset(mlotst_nc) as d:
        mlotst = d["mlotst"].load()
        if "depth" in mlotst.coords:
            mlotst = mlotst.drop_vars("depth")

    ds = xr.Dataset(
        {
            "sst_c": thetao,
            "mld_m": mlotst,
            "sss_psu": so,
        }
    )
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
    start = date.today()
    end = start + timedelta(days=FORECAST_DAYS)
    print(f"Ventana de pronóstico: {start} a {end} ({FORECAST_DAYS} días)")

    rango = f"{start:%Y%m%d}_{end:%Y%m%d}"
    nc_path = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}.nc")
    csv_path = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}.csv")
    thetao_nc = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}_thetao_raw.nc")
    so_nc = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}_so_raw.nc")
    mlotst_nc = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}_mlotst_raw.nc")

    username, password = read_credentials()
    _subset(username, password, DATASET_THETAO, ["thetao"], start, end, thetao_nc, True)
    _subset(username, password, DATASET_SO, ["so"], start, end, so_nc, True)
    _subset(username, password, DATASET_2D, ["mlotst"], start, end, mlotst_nc, False)

    regrid_and_export(thetao_nc, so_nc, mlotst_nc, nc_path, csv_path)

    # Limpiar los crudos por variable: el producto regrillado ya quedó unificado.
    for raw in (thetao_nc, so_nc, mlotst_nc):
        try:
            os.remove(raw)
        except OSError:
            pass

    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
