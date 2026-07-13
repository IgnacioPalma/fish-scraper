"""
Funciones compartidas para los downloaders de SST y CHL.

====================================================================
Grilla unificada — qué, por qué y cómo
====================================================================

Qué hacemos:
    SST y CHL salen de este pipeline en LA MISMA grilla regular de
    1/24° (≈4 km) sobre el bounding box de Atacama. Las coordenadas
    `latitude`/`longitude` son idénticas byte a byte entre los dos
    NetCDF y entre los dos CSV. Por eso un cruce SST↔CHL es un
    `pd.merge(..., on=["time", "latitude", "longitude"])` directo,
    sin regrillado posterior.

Por qué existe:
    Las grillas nativas no coinciden — SST a 0.05° (≈5.5 km),
    CHL L4 a 1/24° (≈4 km). Si dejáramos cada producto en su grilla
    nativa, todo análisis que mezclara las variables tendría que
    regrillar (a mano y arriesgando errores sutiles de alineación).
    Centralizar el regrillado acá lo hace una sola vez, de forma
    consistente y verificable.

Por qué 1/24° y no la grilla de SST:
    1/24° coincide con la grilla nativa de CHL, así CHL queda
    prácticamente intacto (interpolación a sus mismos puntos). Solo
    SST sufre interpolación bilineal desde 0.05° → 1/24°, lo que
    introduce un suavizado leve aceptable para análisis bayesianos
    a escala costera.

Trade-off y cómo revertirlo:
    Si en algún momento se necesita SST en su grilla nativa (por
    ejemplo, fidelidad sub-pixel para fronts oceánicos finos),
    comentar la llamada a `regrid_to_target` dentro de
    `download_sst.py`. La alternativa más rigurosa es un regridder
    conservativo (xesmf), que no agregamos aquí para mantener
    dependencias mínimas.

Implementación:
    - TARGET_LAT, TARGET_LON: arrays numpy con la grilla destino.
    - regrid_to_target(ds): interpola un xarray.Dataset a la grilla
      destino con `method="linear"`.
"""

import os
import sys

import numpy as np
import xarray as xr

from processing.utils.regions import active_region


# Paso de la grilla destino: 1/24° ≈ 4 km, coincide con la grilla nativa de CHL L4
STEP = 1 / 24

# Bounding box del área de estudio — derivado del perfil de región activo
# (processing/utils/regions.py, elegido por la variable de entorno REGION). Se
# conservan estos cuatro nombres porque todos los descargadores Copernicus y
# clean_locations los importan desde acá; cambiar de región es cambiar REGION.
LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = active_region().bbox

TARGET_LAT = np.arange(LAT_MIN, LAT_MAX + STEP / 2, STEP)
TARGET_LON = np.arange(LON_MIN, LON_MAX + STEP / 2, STEP)


def read_credentials() -> tuple[str, str]:
    """Lee las credenciales del entorno; aborta con mensaje claro si faltan."""
    username = os.environ.get("COPERNICUS_USERNAME", "").strip()
    password = os.environ.get("COPERNICUS_PASSWORD", "").strip()

    if not username or not password:
        print(
            "ERROR: faltan credenciales de Copernicus Marine.\n"
            "       Copia .env.example a .env y completa COPERNICUS_USERNAME "
            "y COPERNICUS_PASSWORD antes de ejecutar este script.",
            file=sys.stderr,
        )
        sys.exit(1)

    return username, password


def regrid_to_target(ds: xr.Dataset) -> xr.Dataset:
    """Regrillamos a la grilla destino común para que SST y CHL compartan
    exactamente las mismas coordenadas (interpolación bilineal)."""
    return ds.interp(
        latitude=TARGET_LAT,
        longitude=TARGET_LON,
        method="linear",
    )


def stream_dataset_to_csv(
    ds: xr.Dataset,
    columns: list[str],
    csv_path: str,
    *,
    dropna_how: str = "any",
    transform=None,
    time_chunk: int = 365,
) -> None:
    """Escribe `ds` a CSV recorriendo la dimensión `time` por bloques de
    `time_chunk` pasos, en vez de materializar el cubo completo con un
    único `to_dataframe()`.

    Ese `to_dataframe()` global expande el cubo a una fila por
    celda×día×variable y, sobre el corpus histórico regrillado a 1/24°,
    dispara el pico de memoria: en CI el runner se quedaba sin RAM (OOM)
    y GitHub reportaba "Error: The operation was canceled". Al procesar
    de a un bloque de tiempo el pico queda acotado a ese bloque.

    `transform`, si se entrega, recibe el DataFrame de cada bloque (con
    columnas time/latitude/longitude + las variables de `ds`) y devuelve
    el DataFrame ya con las columnas finales (conversión de unidades,
    renombres). Luego se conservan time/latitude/longitude + `columns` y
    se descartan las filas cuyo subconjunto `columns` es NaN según
    `dropna_how` ("any" bota la fila si falta cualquiera; "all" sólo si
    faltan todas — así una celda costera con parte de las variables no se
    pierde)."""
    n = int(ds.sizes["time"])
    write_header = True
    for start in range(0, n, time_chunk):
        block = ds.isel(time=slice(start, start + time_chunk))
        df = block.to_dataframe().reset_index()
        if transform is not None:
            df = transform(df)
        df = df[["time", "latitude", "longitude", *columns]].dropna(
            subset=columns, how=dropna_how
        )
        df.to_csv(
            csv_path,
            index=False,
            mode="w" if write_header else "a",
            header=write_header,
        )
        write_header = False


def print_summary(df, value_column: str, unit: str) -> None:
    """Imprime resumen final: filas, rango temporal y min/max/mean del valor."""
    values = df[value_column]
    print("\n=== Resumen de la descarga ===")
    print(f"Filas:           {len(df):,}")
    print(f"Rango temporal:  {df['time'].min()} a {df['time'].max()}")
    print(f"Mínimo:          {values.min():.2f} {unit}")
    print(f"Máximo:          {values.max():.2f} {unit}")
    print(f"Promedio:        {values.mean():.2f} {unit}")


def print_summary_da(da: xr.DataArray, name: str, unit: str) -> None:
    """Resumen final calculado directamente sobre el DataArray regrillado,
    sin materializar el DataFrame completo (complemento de
    `stream_dataset_to_csv`, que ya no deja el DataFrame entero a mano).
    Cuenta celdas válidas e informa min/max/mean ignorando los NaN de
    tierra/nubes."""
    valid = int(da.notnull().sum())
    print(f"\n=== Resumen: {name} ===")
    print(f"Celdas válidas:  {valid:,}")
    print(f"Rango temporal:  {da['time'].min().values} a {da['time'].max().values}")
    if valid == 0:
        print("(sin celdas válidas)")
        return
    print(f"Mínimo:          {float(da.min()):.2f} {unit}")
    print(f"Máximo:          {float(da.max()):.2f} {unit}")
    print(f"Promedio:        {float(da.mean()):.2f} {unit}")
