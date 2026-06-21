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
> `data/output/zarpes_atacama_haul_location.csv` (ubicación de lance por zarpe).
> Genéralo antes con las etapas de `processing.locations`.

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

Para cada lance de [zarpes_atacama_haul_location.csv](../../data/output/zarpes_atacama_haul_location.csv)
toma el **día de grilla más cercano** (`sel(time, method="nearest")`) y la **celda más
cercana** de cada capa. Si la celda más cercana es NaN (máscara de tierra), busca la
**celda de mar válida más cercana** dentro de `MAX_FALLBACK_KM` (25 km) y registra la
distancia. Los lances sin coordenadas se conservan con valores nulos. Todas las
covariables son superficiales o integradas en la vertical para no sufrir el enmascarado
costero por profundidad (por eso se descartó la temperatura subsuperficial `thetao`,
cuyo nivel profundo no existe sobre la plataforma costera).

## Diccionario de datos — `data/output/zarpes_atacama_haul_env.csv`

Una fila por zarpe de un solo lance. Hereda todas las columnas de
`zarpes_atacama_haul_location.csv` (identificación del zarpe, captura y ubicación del
lance) y agrega las covariables ambientales + columnas de auditoría.

| Columna | Unidad | Descripción |
|---|---|---|
| `zarpe_id` | — | Identificador único del zarpe (viaje de pesca). |
| `vessel_code` | — | Código interno IFOP de la embarcación. |
| `vessel_name` | — | Nombre de la embarcación. |
| `jack_mackerel_kg` | kg | Captura de jurel del zarpe (variable respuesta del modelo). |
| `haul_lat` | grados | Latitud del lance (centroide del bout de pesca); nula si no se ubicó. |
| `haul_lon` | grados | Longitud del lance; nula si no se ubicó. |
| `haul_start` | ISO 8601 | Inicio de la ventana del lance. |
| `haul_end` | ISO 8601 | Fin de la ventana del lance. |
| `haul_duration_h` | horas | Duración de la ventana del lance. |
| `haul_n_pings` | — | Nº de pings VMS en el bout de pesca. |
| `haul_mean_speed_kt` | nudos | Velocidad media de los pings del lance. |
| `haul_dist_port_km` | km | Distancia del lance al puerto más cercano. |
| `nearest_port` | — | Puerto más cercano al lance. |
| **`sst_c`** | °C | Temperatura superficial del mar (SST) en el lance. |
| **`chl_mg_m3`** | mg/m³ | Clorofila-a superficial (productividad / alimento). |
| **`mld_m`** | m | Profundidad de la capa de mezcla (estructura vertical de la columna). |
| **`sss_psu`** | PSU | Salinidad superficial (discrimina masas de agua / frente subtropical). |
| **`o2_min_mmol_m3`** | mmol/m³ | Mínimo de O₂ disuelto en 0–200 m (techo de la OMZ; comprime el hábitat pelágico). |
| `env_time` | YYYY-MM-DD | Día de la grilla efectivamente muestreado (el más cercano al lance). |
| `env_cell_dist_km` | km | Distancia máxima a una celda muestreada; 0 si todas fueron la celda más cercana, > 0 si hubo fallback costero. |
| `env_status` | — | `ok` (todas exactas) · `fallback` (alguna usó la celda de mar más cercana) · `fuera_de_rango` (lance fuera de la cobertura temporal) · `sin_coords` (lance sin ubicación). |

> **Nota sobre el O₂.** El producto biogeoquímico es de 0.25° (~25 km), la única
> resolución del reanálisis BGC. Su máscara de tierra gruesa empuja a varios lances
> costeros a tomar el O₂ de celdas mar adentro (hasta ~20 km); `env_cell_dist_km`
> registra ese desplazamiento por fila para poder filtrar o ponderar. SSS, MLD, SST y
> CHL muestrean su celda exacta salvo excepciones menores.
