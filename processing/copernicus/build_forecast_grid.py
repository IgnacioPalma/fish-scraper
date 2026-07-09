"""
Arma la GRILLA DE PREDICCIÓN: para cada coordenada de la costa de Atacama y
cada día de pronóstico, las cinco covariables marinas que consume el modelo
de jurel. Es el insumo para correr el modelo entrenado sobre toda la grilla
(mapa de pronóstico), no sólo en los lances observados.

NO descarga nada: une las grillas de pronóstico ya descargadas por
`download_phy_forecast` y `download_bgc_forecast` (ambas regrilladas a la
grilla destino común, así que comparten lat/lon byte a byte).

RELLENO COSTERO (por qué no se hace un drop simple): las capas tienen máscaras
de tierra DISTINTAS — la grilla física (1/12°) enmascara más celdas pegadas a
la costa que la biogeoquímica (1/4°, más gruesa). Un `dropna(how="any")` botaría
toda esa franja nerítica (donde justamente ocurre la pesca), dejando huecos en
los mapas. En cambio:
  - Se CONSERVA toda celda que AL MENOS UNA capa considere mar (>= 1 valor).
  - En esas celdas, las covariables que sí quedaron NaN se rellenan con el valor
    de la celda de mar válida más cercana de ESA MISMA capa (haversine, dentro
    de MAX_FALLBACK_KM), igual que el fallback costero de `sample_haul_environment`.
  - Sólo se descartan las celdas que las CINCO capas enmascaran (continente real).
La columna `coast_filled` marca las celdas donde al menos una covariable se
rellenó por vecino, para poder estilizarlas o auditarlas en los plots.

Entrada (en data/copernicus/, se globa por base; tolera varias corridas):
    phy_forecast_atacama_*.nc   → sst_c, mld_m, sss_psu
    bgc_forecast_atacama_*.nc   → chl_mg_m3, o2_min_mmol_m3

Salida:
    data/output/copernicus/copernicus_forecast_grid_<rango>.csv
        columnas: time, latitude, longitude,
                  sst_c, chl_mg_m3, mld_m, sss_psu, o2_min_mmol_m3, coast_filled
    data/output/copernicus/diccionario_copernicus_forecast_grid.md

Uso:
    uv run python -m processing.copernicus.build_forecast_grid
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.spatial import cKDTree

COPERNICUS_DIR = Path(__file__).resolve().parents[2] / "data" / "copernicus"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "output" / "copernicus"

# (base del archivo, columnas que aporta)
PRODUCTS = [
    ("phy_forecast_atacama", ["sst_c", "mld_m", "sss_psu"]),
    ("bgc_forecast_atacama", ["chl_mg_m3", "o2_min_mmol_m3"]),
]

# Orden final de las covariables (= features del modelo).
FEATURES = ["sst_c", "chl_mg_m3", "mld_m", "sss_psu", "o2_min_mmol_m3"]

EARTH_RADIUS_KM = 6371.0
# Radio máximo para rellenar una celda costera con la celda de mar más cercana
# de la misma capa (consistente con sample_haul_environment.MAX_FALLBACK_KM).
MAX_FALLBACK_KM = 25.0


def _abrir_producto(base: str) -> xr.Dataset:
    """Une todos los `<base>_*.nc` de data/copernicus en un Dataset por tiempo.

    Tolera varias corridas (un archivo por ventana de pronóstico): concatena
    por tiempo, ordena y deja un día por tiempo (el último, que proviene del
    pronóstico más reciente)."""
    paths = sorted(COPERNICUS_DIR.glob(f"{base}_*.nc"))
    if not paths:
        sys.exit(
            f"No se encontró ninguna grilla `{base}_*.nc` en {COPERNICUS_DIR}.\n"
            f"Generala con `uv run python -m processing.copernicus.download_"
            f"{base.split('_')[0]}_forecast` antes de armar la grilla."
        )
    datasets = [xr.open_dataset(p) for p in paths]
    # join="exact": todos deben compartir exactamente la grilla destino común;
    # si alguno trae otra grilla (p.ej. un crudo `_raw` que quedó por una
    # descarga interrumpida), falla en vez de alinear con join externo y
    # rellenar NaN en silencio.
    ds = (
        xr.concat(datasets, dim="time", join="exact")
        if len(datasets) > 1
        else datasets[0]
    )
    ds = ds.sortby("time").drop_duplicates("time", keep="last")
    return ds


def _to_frame(base: str, cols: list[str]) -> pd.DataFrame:
    ds = _abrir_producto(base)
    df = ds[cols].to_dataframe().reset_index()
    return df[["time", "latitude", "longitude", *cols]]


def _latlon_to_xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Vectores unitarios en la esfera (para que el vecino más cercano euclídeo
    en cKDTree equivalga al de círculo máximo)."""
    lat_r, lon_r = np.radians(lat), np.radians(lon)
    cos_lat = np.cos(lat_r)
    return np.column_stack(
        (cos_lat * np.cos(lon_r), cos_lat * np.sin(lon_r), np.sin(lat_r))
    )


def _chord_to_km(chord: np.ndarray) -> np.ndarray:
    """Convierte la distancia de cuerda (entre vectores unitarios) a km de
    círculo máximo."""
    return EARTH_RADIUS_KM * 2.0 * np.arcsin(np.clip(chord / 2.0, 0.0, 1.0))


def _fill_coastal(grid: pd.DataFrame) -> pd.DataFrame:
    """Rellena, por día, las covariables NaN de cada celda costera con el valor
    de la celda de mar válida más cercana de la misma capa (dentro de
    MAX_FALLBACK_KM). Trabaja sólo sobre celdas ya conservadas (>= 1 capa con
    valor). Marca `coast_filled` y devuelve el frame con los huecos rellenados."""
    grid = grid.copy()
    grid["coast_filled"] = False

    for _, idx in grid.groupby("time").groups.items():
        sub = grid.loc[idx]
        xyz = _latlon_to_xyz(sub["latitude"].to_numpy(), sub["longitude"].to_numpy())
        pos = np.asarray(idx)
        for var in FEATURES:
            vals = sub[var].to_numpy()
            valid = np.isfinite(vals)
            missing = ~valid
            if not missing.any() or not valid.any():
                continue
            tree = cKDTree(xyz[valid])
            chord, nn = tree.query(xyz[missing])
            within = _chord_to_km(chord) <= MAX_FALLBACK_KM
            if not within.any():
                continue
            target_rows = pos[missing][within]
            source_vals = vals[valid][nn[within]]
            grid.loc[target_rows, var] = source_vals
            grid.loc[target_rows, "coast_filled"] = True

    return grid


def _escribir_diccionario(path: Path) -> None:
    contenido = """# Diccionario · copernicus_forecast_grid

Grilla de PRONÓSTICO para predecir con el modelo de jurel: una fila por celda
de mar de la grilla de Atacama (1/24° ≈ 4 km) y por día de pronóstico
(horizonte ~10 días del sistema operacional global Copernicus). Incluye la
franja nerítica: las celdas costeras que alguna capa enmascara se rellenan con
la celda de mar válida más cercana de esa misma capa (ver `coast_filled`);
sólo se descarta el continente real (las cinco capas NaN).

| columna           | unidad   | descripción | fuente Copernicus (`anfc`) |
|-------------------|----------|-------------|----------------------------|
| `time`            | fecha    | día de pronóstico | — |
| `latitude`        | grados   | centro de celda (grilla destino común) | — |
| `longitude`       | grados   | centro de celda (grilla destino común) | — |
| `sst_c`           | °C       | temperatura superficial (modelo) | PHY `thetao` @ 0 m |
| `chl_mg_m3`       | mg/m³    | clorofila superficial | BGC `chl` @ 0 m |
| `mld_m`           | m        | profundidad de capa de mezcla | PHY `mlotst` |
| `sss_psu`         | PSU      | salinidad superficial | PHY `so` @ 0 m |
| `o2_min_mmol_m3`  | mmol/m³  | mínimo de O₂ 0–200 m (techo OMZ) | BGC `o2` |
| `coast_filled`    | bool     | True si ≥1 covariable se rellenó por vecino costero | — |

CAVEAT `sst_c`: el modelo se entrenó con SST observada OSTIA L4
(`analysed_sst`); para días futuros no hay observación, así que el pronóstico
usa la temperatura superficial del modelo físico (`thetao` @ 0 m). Misma
unidad (°C), fuente distinta.

Generado por `processing.copernicus.build_forecast_grid`.
"""
    path.write_text(contenido)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    print("Abriendo grillas de pronóstico (phy + bgc)...")

    frames = [_to_frame(base, cols) for base, cols in PRODUCTS]

    grid = frames[0]
    for f in frames[1:]:
        grid = grid.merge(f, on=["time", "latitude", "longitude"], how="outer")

    # Conservar toda celda que AL MENOS UNA capa considere mar; el continente
    # real (las cinco capas NaN) se descarta.
    n_total = len(grid)
    grid = grid.dropna(subset=FEATURES, how="all").reset_index(drop=True)

    # Relleno costero: completar las covariables enmascaradas por la celda de
    # mar más cercana de la misma capa (recupera la franja nerítica).
    grid = _fill_coastal(grid)
    n_filled = int(grid["coast_filled"].sum())

    # Tras el relleno, descartar lo que aún tenga huecos (capa sin vecino válido
    # dentro de MAX_FALLBACK_KM); raro.
    n_keep = len(grid)
    grid = grid.dropna(subset=FEATURES, how="any")
    n_drop_resid = n_keep - len(grid)

    grid = grid[["time", "latitude", "longitude", *FEATURES, "coast_filled"]].sort_values(
        ["time", "latitude", "longitude"]
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dias = sorted(pd.to_datetime(grid["time"]).dt.strftime("%Y%m%d").unique())
    rango = f"{dias[0]}_{dias[-1]}" if dias else "vacio"
    out_csv = OUTPUT_DIR / f"copernicus_forecast_grid_{rango}.csv"
    grid.to_csv(out_csv, index=False)
    _escribir_diccionario(OUTPUT_DIR / "diccionario_copernicus_forecast_grid.md")

    # --- Resumen ---------------------------------------------------------
    print(f"\nCeldas totales (mar+tierra): {n_total:,}")
    print(f"Celdas conservadas (mar):    {len(grid):,}")
    print(f"  de ellas rellenadas costa: {n_filled:,} (coast_filled=True)")
    if n_drop_resid:
        print(f"  descartadas sin vecino:    {n_drop_resid:,} (> {MAX_FALLBACK_KM:.0f} km)")
    print(f"Días de pronóstico:          {len(dias)}  ({rango})")
    if len(grid):
        print(f"Celdas por día:              ~{len(grid) // max(len(dias), 1):,}")
        print("Covariables (mín / media / máx):")
        for col in FEATURES:
            s = grid[col]
            print(f"  {col:>15}: {s.min():.3f} / {s.mean():.3f} / {s.max():.3f}")
    print(f"\nArchivo generado:\n  {out_csv}")


if __name__ == "__main__":
    main()
