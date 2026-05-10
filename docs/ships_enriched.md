# Diccionario de datos — `data/ships_enriched.csv`

## Resumen de las columnas nuevas

`enrich_ships` agrega **3 columnas posicionales fijas** + una columna por cada variable presente en los NetCDF descargados. Si en `data/` están los seis NetCDF (SST, CHL, PHY, BGC, SLA, WIND), se agregan **16 columnas de valor**. Si sólo están SST + CHL, se agregan **2** y el resto del CSV no aparece — backward-compatible.

### Columnas posicionales (siempre)

| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| `LAT_GRILLA` | float64 | grados decimales | derivada |
| `LON_GRILLA` | float64 | grados decimales | derivada |
| `DISTANCIA_KM_GRILLA` | float64 | km | derivada |

### Columnas de valor (según los NetCDF presentes)

| Columna | Familia | Unidad | Producto upstream | Notas |
|---|---|---|---|---|
| `analysed_sst_celsius` | SST | °C | `METOFFICE-GLO-SST-L4-REP-OBS-SST` (0.05° → 1/24°) | Variable primaria |
| `chl_mg_m3` | CHL | mg/m³ | `cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D` (1/24° nativo) | Variable primaria |
| `mlotst` | PHY | m | `cmems_mod_glo_phy_my_0.083deg_P1D-m` (1/12° → 1/24°) | Mixed Layer Depth |
| `so_0m` | PHY | PSU | mismo | Salinidad superficial |
| `thetao_400m` | PHY | °C | mismo | Temperatura potencial a ~400 m (techo del refugio térmico de jurel) |
| `o2_min_0_200m` | BGC | mmol/m³ | `cmems_mod_glo_bgc_my_0.25deg_P1D-m` (0.25° → 1/24°) | Mínimo de O₂ en columna 0–200 m (proxy del techo de la OMZ) |
| `nppv` | BGC | mg C/m³/día | mismo | Producción primaria neta vertical en superficie |
| `sla` | SLA | m | `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D` (0.125° → 1/24°) | Anomalía del nivel del mar |
| `adt` | SLA | m | mismo | Topografía dinámica absoluta |
| `ugos` | SLA | m/s | mismo | Velocidad geostrófica zonal |
| `vgos` | SLA | m/s | mismo | Velocidad geostrófica meridional |
| `eastward_wind` | WIND | m/s | `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` (0.125° → 1/24°, agregado a media diaria) | Componente zonal del viento a 10 m |
| `northward_wind` | WIND | m/s | mismo | Componente meridional del viento a 10 m |

> **Sobre `phyc`/`zooc`**: el reanálisis BGC global (`GLOBAL_MULTIYEAR_BGC_001_029`) no expone biomasa de fitoplancton ni de zooplancton para 2017–2022 (sólo `chl, no3, nppv, o2, po4, si`). Quedan fuera del flujo. Como proxy de productividad usamos `nppv`.

## Reglas de NaN

A diferencia de la versión que sólo cruzaba SST + CHL, **las columnas no se llenan en bloque**. Hay dos niveles de NaN:

### 1. NaN "estructural" — el lance no es elegible para enriquecerse

**Todas** las columnas nuevas quedan en NaN si se cumple cualquiera de las condiciones siguientes (mutuamente excluyentes en el conteo del resumen):

| Causa | Detalle |
|---|---|
| Sin coordenada | `LATITUD_DD` o `LONGITUD_DD` es NaN (DMS original malformado) |
| Sin fecha UTC | `FECHA_HORA_ZARPE_UTC` es NaN (DST gap o fecha original malformada) |
| Fuera del bbox | (lat, lon) ∉ [−29, −25] × [−72, −70] |
| Fuera de rango temporal | Fecha ∉ [2017-01-01, 2022-12-31] |
| Sin día en la grilla | El día UTC no aparece en los NetCDF (gaps esporádicos) |
| Sin celdas válidas | Ese día la grilla está totalmente cubierta por nubes/tierra (cero celdas con SST y CHL no-nulas) |

El resumen impreso por el script lista los conteos por causa. En el run de referencia (sólo SST + CHL): 11,541 / 11,580 enriquecidas (99.66%).

### 2. NaN "por variable" — el lance se enriqueció pero la celda no tiene datos para esa variable

Una vez que se elige la celda más cercana (basándose en SST y CHL no-nulas), las **demás variables se muestrean tal cual** en esa celda. Si la celda elegida cae sobre tierra para SLA (común cerca de la costa), o en un día que no estaba cubierto por el producto WIND, esa columna específica queda NaN aunque las columnas posicionales y SST/CHL sean válidas.

Esto es **deliberado**: si exigiéramos que las 13 variables fueran simultáneamente no-nulas para definir una celda válida, el conjunto utilizable se reduciría drásticamente en la franja costera. Conservar la celda elegida por SST + CHL maximiza la cobertura de filas; el modelo downstream decide qué hacer con los NaN por variable (imputación, exclusión, mascara per-variable, etc.).

Convenciones útiles para el análisis posterior:

- `NaN` en las columnas posicionales (`LAT_GRILLA`, `LON_GRILLA`) ⇒ NaN estructural ⇒ todas las variables son NaN para esa fila.
- `NaN` sólo en una columna de valor ⇒ NaN por variable ⇒ el lance sí fue enriquecido y otras columnas pueden ser válidas.

## Detalle por familia

### Posicionales: `LAT_GRILLA`, `LON_GRILLA`

Coordenadas en grados decimales (signo negativo en sur/oeste) de la celda de la **grilla compartida 1/24°** (≈4 km) más cercana al lance, donde tanto SST como CHL están presentes ese día.

La grilla canónica está definida en [utils/cmems_common.py](../utils/cmems_common.py):

- `TARGET_LAT`: 95 puntos, paso 1/24°, entre −29.0 y −25.0.
- `TARGET_LON`: 36 puntos, paso 1/24°, entre −72.0 y −70.0.

**Garantía**: estos valores son byte-idénticos a los de las columnas `latitude`/`longitude` en cualquiera de los CSV de productos (SST, CHL, PHY, BGC, SLA, WIND). Un merge directo es válido:

```python
import pandas as pd
ships = pd.read_csv("data/ships_enriched.csv", sep=";")
sst   = pd.read_csv("data/sst_atacama_2017_2022.csv")
joined = pd.merge(
    ships, sst,
    left_on=["FECHA_HORA_ZARPE_UTC", "LAT_GRILLA", "LON_GRILLA"],
    right_on=["time", "latitude", "longitude"],
)
# joined.analysed_sst_celsius_x == joined.analysed_sst_celsius_y (verificado)
```

### Posicional: `DISTANCIA_KM_GRILLA`

Distancia aproximada del lance a la celda elegida, en kilómetros. Calculada en una proyección equirectangular local centrada en −27° (longitud escalada por `cos(−27°) ≈ 0.891`) y luego convertida a km con factor 111.32 km/°. El error vs. la distancia haversine real es <0.5% sobre el bbox de Atacama.

Distribución observada: media ≈ 2 km, mediana < 2 km, máximo ≈ 15 km. Sirve como **métrica de calidad del match**: distancias altas pueden indicar cobertura nubosa intensa que día (la celda más cercana con datos quedó lejos del lance real). Para análisis estrictos puede ser útil filtrar `DISTANCIA_KM_GRILLA > 10` y dejar esos casos como NaN.

### SST — `analysed_sst_celsius`

Sea Surface Temperature en grados Celsius en la celda matched, ese día UTC. Producto upstream: Copernicus L4 reprocesado `METOFFICE-GLO-SST-L4-REP-OBS-SST` (analizado, gap-free, diario, ~5 km nativos regrilados a 1/24° vía bilineal — ver [downloads/download_sst.py](../downloads/download_sst.py)). El nombre se mantiene idéntico al del CSV upstream para permitir merges sin renombres.

### CHL — `chl_mg_m3`

Clorofila-a superficial en mg/m³ en la celda matched, ese día UTC. Producto upstream: Copernicus L4 multi-sensor gap-free `cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D` (ya nativo a 4 km / 1/24°, sin regrillado — ver [downloads/download_chl.py](../downloads/download_chl.py)). Aunque el producto es "gap-free", queda NaN sobre tierra y en outages raros del sensor. La distribución es muy asimétrica (mucho rango bajo + cola larga durante eventos de surgencia).

### PHY — `mlotst`, `so_0m`, `thetao_400m`

Tres campos derivados del reanálisis físico Mercator GLORYS12 (`cmems_mod_glo_phy_my_0.083deg_P1D-m`, 1/12° regrillado a 1/24° — ver [downloads/download_phy.py](../downloads/download_phy.py)):

- **`mlotst`** (m): Mixed Layer Depth diaria, ya 2-D en el producto upstream. Cuanto más profunda la capa de mezcla, más eficiente la mezcla térmica/nutricional vertical.
- **`so_0m`** (PSU): salinidad práctica en superficie, seleccionada del nivel más cercano a 0 m. Útil para detectar el Frente Subtropical (jurel suele asociarse a la convergencia salinidad/temperatura).
- **`thetao_400m`** (°C): temperatura potencial al nivel más cercano a 400 m. Indica el techo del refugio térmico que jurel usa durante el día.

### BGC — `o2_min_0_200m`, `nppv`

Dos campos derivados del reanálisis biogeoquímico (`cmems_mod_glo_bgc_my_0.25deg_P1D-m`, 0.25° regrillado a 1/24° — ver [downloads/download_bgc.py](../downloads/download_bgc.py)):

- **`o2_min_0_200m`** (mmol/m³): oxígeno disuelto **mínimo en la columna 0–200 m**. Proxy del techo de la zona de mínima oxigenación (OMZ) frente a Atacama. Valores bajos indican OMZ poco profunda — barrera vertical para jurel.
- **`nppv`** (mg C/m³/día): producción primaria neta vertical en superficie. Proxy de productividad pelágica.

El producto BGC global no incluye `phyc`/`zooc` para 2017–2022; ver el aviso al inicio.

### SLA — `sla`, `adt`, `ugos`, `vgos`

Cuatro campos altimétricos del producto DUACS multi-misión (`cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D`, 0.125° regrillado a 1/24° — ver [downloads/download_sla.py](../downloads/download_sla.py)):

- **`sla`** (m): anomalía del nivel del mar. Un campo positivo/negativo señala remolinos anticiclónicos/ciclónicos respectivamente.
- **`adt`** (m): topografía dinámica absoluta = SLA + media multianual. Útil para localizar fronts permanentes.
- **`ugos`, `vgos`** (m/s): componentes zonal y meridional de la velocidad geostrófica derivadas del gradiente de ADT. Permiten calcular vorticidad y divergencia downstream.

Los gradientes de SLA/ADT y la vorticidad son features altamente predictivas de agregaciones pelágicas — pero deben computarse en post-proceso a partir de las columnas crudas.

### WIND — `eastward_wind`, `northward_wind`

Componentes zonal (`u10`) y meridional (`v10`) del viento a 10 m, agregadas a **media diaria** desde el producto horario (`cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H`, 0.125° regrillado a 1/24° — ver [downloads/download_wind.py](../downloads/download_wind.py)).

Para un índice de surgencia tipo Bakun en la costa de Atacama (orientada N-S), la componente alongshore es aproximadamente `northward_wind`; valores negativos (viento al sur, favorable a surgencia equatoriana) son los que mecanizan la surgencia costera. Calcular `wind_speed = sqrt(u² + v²)` y `wind_dir = atan2(v, u)` en post-proceso es trivial.

## Cómo se computa el match

Pseudocódigo del algoritmo (implementación real en [enrich/enrich_ships.py](../enrich/enrich_ships.py)):

```
1. Cargar SST y CHL desde los .nc, convertir SST K→°C, fusionar en un Dataset.
2. Si están presentes, abrir también phy_*.nc, bgc_*.nc, sla_*.nc, wind_*.nc
   y mergearlos al Dataset combinado (xr.merge join="outer"). Cada NetCDF
   ausente se anuncia con un aviso por stderr y se salta — backward-compatible.
3. Para cada lance, marcar como inelegible si:
     - LATITUD_DD o LONGITUD_DD es NaN
     - FECHA_HORA_ZARPE_UTC es NaN
     - (lat, lon) cae fuera del bbox de la grilla
     - fecha cae fuera de [2017-01-01, 2022-12-31]
4. Para cada fecha única (entre los lances elegibles):
     a. Slice del Dataset al día (ds.sel(time=fecha))
     b. Mascara las celdas con AMBAS variables PRIMARIAS (SST y CHL) no-nulas
     c. Si no quedan celdas → marcar todos los lances de ese día con NaN
     d. Construir cKDTree sobre las celdas válidas en proyección
        equirectangular local (lon * cos(-27°), lat)
     e. Query vectorizada con todos los lances del día → para cada lance,
        índice de celda más cercana + distancia
     f. Para CADA variable en el Dataset combinado, muestrear su valor en la
        celda elegida (puede ser NaN si la variable no tiene cobertura ahí —
        ver "NaN por variable" más arriba).
     g. Asignar LAT_GRILLA, LON_GRILLA, DISTANCIA_KM_GRILLA + todas las
        columnas de valor.
5. Escribir ships_enriched.csv (sep=";").
```

## Columnas heredadas relevantes para el match

Estas tres columnas ya existían en `ships_filtered.csv` y son las que determinan el resultado del enriquecimiento:

| Columna | Tipo | Origen | Rol |
|---|---|---|---|
| `LATITUD_DD` | float64, grados decimales | [filter_ships.py:dms_serie_a_decimal](../filters/filter_ships.py) sobre `LATITUD` (DMS empacado) | Entrada espacial al KDTree |
| `LONGITUD_DD` | float64, grados decimales | [filter_ships.py:dms_serie_a_decimal](../filters/filter_ships.py) sobre `LONGITUD` (DMS empacado) | Entrada espacial al KDTree |
| `FECHA_HORA_ZARPE_UTC` | string `YYYY-MM-DD` | [filter_ships.py:fecha_zarpe_a_utc_date](../filters/filter_ships.py) sobre `FECHA_HORA_ZARPE` (hora local Chile) | Slice temporal de los NetCDF |

Las columnas SERNAPESCA originales (`BARCO`, `FECHA_HORA_ZARPE`, `LATITUD`, `LONGITUD`, `ESPECIE`, `CAPTURA`, etc.) se preservan sin modificar.

## Reproducir

```bash
docker compose run --rm filter_ships    # ships.csv → ships_filtered.csv

# Capas (las dos primeras son obligatorias; el resto es opcional)
docker compose run --rm download_sst
docker compose run --rm download_chl
docker compose run --rm download_phy
docker compose run --rm download_bgc
docker compose run --rm download_sla
docker compose run --rm download_wind

# o todo de una sola vez (corta a la primera falla)
docker compose run --rm download_all

docker compose run --rm enrich_ships    # ships_filtered.csv → ships_enriched.csv
```

Requiere que existan previamente:

- `data/ships.csv` (insumo SERNAPESCA).
- `data/sst_atacama_2017_2022.nc` (de `download_sst`) — obligatorio.
- `data/chl_atacama_2017_2022.nc` (de `download_chl`) — obligatorio.
- `data/phy_atacama_2017_2022.nc`, `bgc_atacama_2017_2022.nc`, `sla_atacama_2017_2022.nc`, `wind_atacama_2017_2022.nc` — opcionales. Si faltan, las columnas correspondientes quedan NaN y el script imprime un aviso.
