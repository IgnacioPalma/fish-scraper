# Pipeline Copernicus (capas marinas → lances)

Descarga las capas oceánicas del Copernicus Marine Data Service para la costa de
Atacama y las muestrea en la ubicación y día de cada lance de jurel, dejando un
dataset por lance enriquecido con covariables ambientales para el modelo bayesiano.

Cada descargador escribe NetCDF + CSV sobre la **grilla destino común** (1/24° ≈ 4 km,
`TARGET_LAT`/`TARGET_LON` en [../utils/cmems_common.py](../utils/cmems_common.py)) y el
**bounding box** de Atacama (lat −29 a −25, lon −72 a −70). El rango temporal sale del
rango global del proyecto ([../utils/date_ranges.py](../utils/date_ranges.py),
2023-01-01 a 2024-12-31), intersectado con la disponibilidad de cada producto.

> La etapa de muestreo depende del pipeline de localizaciones: necesita
> `data/processing/locations/single_haul/zarpes_atacama_haul_single.csv` (zarpes de un único lance confiable).
> Genéralo antes con las etapas de `processing.locations` (hasta `single_haul.filter_single_haul`).

## Ejecutar el pipeline completo

Requiere credenciales Copernicus en `.env` (`COPERNICUS_USERNAME` /
`COPERNICUS_PASSWORD`) y conexión a internet; las descargas son lentas.

```bash
uv run python -m processing.copernicus.run_pipeline
# Reutiliza las grillas ya descargadas y arranca desde el muestreo:
uv run python -m processing.copernicus.run_pipeline --skip-download
```

Cada etapa también se puede correr por separado (en orden):

```bash
uv run python -m processing.copernicus.download_sst              # → sst_atacama_<rango>.{nc,csv}
uv run python -m processing.copernicus.download_chl              # → chl_atacama_<rango>.{nc,csv}
uv run python -m processing.copernicus.download_phy              # → phy_atacama_<rango>.{nc,csv}
uv run python -m processing.copernicus.download_bgc              # → bgc_atacama_<rango>.{nc,csv}
uv run python -m processing.copernicus.sample_haul_environment  # → data/output/zarpes_atacama_haul_env.csv
```

## Etapas

| # | Módulo | Salida | Variable(s) que aporta al lance |
|---|---|---|---|
| 1 | `download_sst` | `data/copernicus/sst_atacama_<rango>.{nc,csv}` | `sst_c` |
| 2 | `download_chl` | `data/copernicus/chl_atacama_<rango>.{nc,csv}` | `chl_mg_m3` |
| 3 | `download_phy` | `data/copernicus/phy_atacama_<rango>.{nc,csv}` | `mld_m`, `sss_psu` |
| 4 | `download_bgc` | `data/copernicus/bgc_atacama_<rango>.{nc,csv}` | `o2_min_mmol_m3` |
| 5 | `sample_haul_environment` | `data/output/zarpes_atacama_haul_env.csv` | (producto final) |

> Las capas `download_sla` (altimetría) y `download_wind` (viento) también viven en
> este paquete pero **no** alimentan el producto de lances; se descargan por separado
> si se necesitan como covariables adicionales.

### 1–4. Descargadores

Uno por capa. Descargan un subconjunto del producto Copernicus, reducen a campos 2-D
(PHY y BGC colapsan la dimensión de profundidad: PHY toma `mlotst` 2-D + `so`/`thetao`
en niveles; BGC toma el **mínimo de O₂ en 0–200 m** como proxy del techo de la OMZ y
`nppv` superficial), regrillan a la grilla común y reescriben el NetCDF + CSV. SST se
convierte de Kelvin a °C; CHL queda en mg/m³. Si Copernicus renombra un `DATASET_ID`,
ver la sección *"Solución de problemas"* y actualizar la constante al inicio del módulo.

### 5. Muestreo en lances — `sample_haul_environment.py`

Para cada lance de [zarpes_atacama_haul_single.csv](../../data/processing/locations/single_haul/zarpes_atacama_haul_single.csv)
toma el **día de grilla más cercano** (`sel(time, method="nearest")`) y la **celda más
cercana** de cada capa. Si la celda más cercana es NaN (máscara de tierra), busca la
**celda de mar válida más cercana** dentro de `MAX_FALLBACK_KM` (25 km) y registra la
distancia. Los lances sin coordenadas se conservan con valores nulos. Todas las
covariables son superficiales o integradas en la vertical para no sufrir el enmascarado
costero por profundidad (por eso se descartó la temperatura subsuperficial `thetao`,
cuyo nivel profundo no existe sobre la plataforma costera).

## Diccionario de datos

El detalle por columna del producto final `data/output/zarpes_atacama_haul_env.csv`
vive junto al dataset en
[data/output/diccionario_haul_env.md](../../data/output/diccionario_haul_env.md).
