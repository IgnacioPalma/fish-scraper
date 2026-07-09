"""
Descarga el PRONÓSTICO biogeoquímico de Copernicus Marine para la costa de
Atacama (lat -29 a -25, lon -72 a -70) a partir del producto operacional
GLOBAL_ANALYSISFORECAST_BGC_001_028 (Mercator, análisis + 10 días de
forecast, diario, 1/4°). De ese producto extrae las dos covariables
biogeoquímicas que alimentan el modelo de jurel, ya con sus nombres finales
de columna:

    chl_mg_m3       ← chl @ superficie        clorofila superficial (mg/m³)
    o2_min_mmol_m3  ← o2 mínimo 0–200 m       techo de la OMZ (mmol/m³)

Diferencia con `download_bgc.py` (reanálisis `_my_`, histórico):
  - Apunta a los datasets de ANÁLISIS Y PRONÓSTICO (`anfc`), no al reanálisis.
  - El rango temporal NO viene del rango global del proyecto (histórico),
    sino de una ventana DINÁMICA hacia adelante: desde hoy hasta hoy +
    FORECAST_DAYS (~10 días, horizonte máximo del sistema operacional global).
  - En el sistema operacional las variables están separadas en datasets por
    familia (o2 en `bio`, chl en `pft`), así que se hacen dos llamadas a
    `copernicusmarine.subset()` y se unen con `xr.merge`.

El producto BGC viene a 0.25° (≈25 km); el regrillado bilineal a 1/24°
suaviza la señal — no agrega información, sólo la lleva a la grilla
compartida para que el merge downstream sea trivial.

Las credenciales se leen de COPERNICUS_USERNAME / COPERNICUS_PASSWORD
(cargadas desde .env mediante python-dotenv).

Uso:
    uv run python -m processing.copernicus.download_bgc_forecast
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

# Datasets `anfc` del producto GLOBAL_ANALYSISFORECAST_BGC_001_028.
# o2 vive en la familia `bio`, chl en `pft`. Si Copernicus los renombra,
# ver README ("Solución de problemas").
DATASET_BIO = "cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m"
DATASET_PFT = "cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m"

# Rango vertical: 0–200 m cubre la columna donde está el techo de la OMZ
# frente a Atacama. Para chl tomamos sólo el nivel superficial.
DEPTH_MIN = 0.0
DEPTH_MAX = 200.0
DEPTH_SURFACE = 0.0

OUTPUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "copernicus")
FILENAME_BASE = "bgc_forecast_atacama"

OUTPUT_VARIABLES = {
    "chl_mg_m3": "mg/m³",
    "o2_min_mmol_m3": "mmol/m³",
}


def _subset(
    username: str,
    password: str,
    dataset_id: str,
    variables: list[str],
    start: date,
    end: date,
    nc_path: str,
) -> str:
    """Descarga un subconjunto NetCDF (0–200 m) de un dataset y devuelve su ruta."""
    print(
        f"Descargando {variables} de {dataset_id}\n"
        f"  Rango efectivo:  {start} a {end}\n"
        f"  Latitud:         {LAT_MIN} a {LAT_MAX}\n"
        f"  Longitud:        {LON_MIN} a {LON_MAX}\n"
        f"  Profundidad:     {DEPTH_MIN} m a {DEPTH_MAX} m"
    )
    try:
        copernicusmarine.subset(
            dataset_id=dataset_id,
            variables=variables,
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


def _surface(da: xr.DataArray) -> xr.DataArray:
    """Selecciona el nivel superficial y descarta la coord escalar `depth`."""
    selected = da.sel(depth=DEPTH_SURFACE, method="nearest")
    if "depth" in selected.coords:
        selected = selected.drop_vars("depth")
    return selected


def regrid_and_export(bio_nc: str, pft_nc: str, nc_path: str, csv_path: str) -> str:
    """Reduce o2 a su mínimo 0–200 m y chl a superficie, arma las covariables
    con su nombre final, regrilla a la grilla destino común, reescribe el
    NetCDF y exporta el CSV."""
    print("Reduciendo profundidades y regrillando el pronóstico biogeoquímico...")

    with xr.open_dataset(bio_nc) as d:
        o2_min = d["o2"].load().min(dim="depth", skipna=True)
    with xr.open_dataset(pft_nc) as d:
        chl = _surface(d["chl"].load())

    ds = xr.Dataset(
        {
            "chl_mg_m3": chl,
            "o2_min_mmol_m3": o2_min,
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
    bio_nc = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}_bio_raw.nc")
    pft_nc = os.path.join(OUTPUT_DIR, f"{FILENAME_BASE}_{rango}_pft_raw.nc")

    username, password = read_credentials()
    _subset(username, password, DATASET_BIO, ["o2"], start, end, bio_nc)
    _subset(username, password, DATASET_PFT, ["chl"], start, end, pft_nc)

    regrid_and_export(bio_nc, pft_nc, nc_path, csv_path)

    for raw in (bio_nc, pft_nc):
        try:
            os.remove(raw)
        except OSError:
            pass

    print(f"\nArchivos generados:\n  {nc_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
