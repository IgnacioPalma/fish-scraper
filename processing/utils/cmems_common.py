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


# Paso de la grilla destino: 1/24° ≈ 4 km, coincide con la grilla nativa de CHL L4
STEP = 1 / 24

# Bounding box de Atacama (mismo para SST y CHL)
TARGET_LAT = np.arange(-29.0, -25.0 + STEP / 2, STEP)
TARGET_LON = np.arange(-72.0, -70.0 + STEP / 2, STEP)


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


def print_summary(df, value_column: str, unit: str) -> None:
    """Imprime resumen final: filas, rango temporal y min/max/mean del valor."""
    values = df[value_column]
    print("\n=== Resumen de la descarga ===")
    print(f"Filas:           {len(df):,}")
    print(f"Rango temporal:  {df['time'].min()} a {df['time'].max()}")
    print(f"Mínimo:          {values.min():.2f} {unit}")
    print(f"Máximo:          {values.max():.2f} {unit}")
    print(f"Promedio:        {values.mean():.2f} {unit}")
