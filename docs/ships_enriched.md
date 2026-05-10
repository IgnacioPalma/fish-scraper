# Diccionario de datos — `data/ships_enriched.csv`

## Resumen de las columnas nuevas

| Columna | Tipo | Unidad | Rango observado | Origen |
|---|---|---|---|---|
| `LAT_GRILLA` | float64 | grados decimales | [−29.0, −25.0] | derivada |
| `LON_GRILLA` | float64 | grados decimales | [−72.0, −70.0] | derivada |
| `DISTANCIA_KM_GRILLA` | float64 | km | ~0 a ~15 | derivada |
| `analysed_sst_celsius` | float64 | °C | ~12 a ~23 | Copernicus L4 SST |
| `chl_mg_m3` | float64 | mg/m³ | ~0.14 a ~32 | Copernicus L4 CHL |

Las cinco columnas se llenan **en bloque** o quedan **todas en NaN** para una misma fila — nunca se mezcla "SST sí, CHL no": el algoritmo busca explícitamente la celda más cercana donde AMBAS variables son no-nulas el mismo día.

### Causas de NaN en las columnas nuevas

Una fila queda con las cinco columnas en NaN si se cumple cualquiera de estas condiciones (mutuamente excluyentes en el conteo del resumen):

| Causa | Conteo observado | Detalle |
|---|---|---|
| Sin coordenada | 28 | `LATITUD_DD` o `LONGITUD_DD` es NaN (DMS original malformado) |
| Sin fecha UTC | 4 | `FECHA_HORA_ZARPE_UTC` es NaN (DST gap o fecha original malformada) |
| Fuera del bbox | 7 | (lat, lon) ∉ [−29, −25] × [−72, −70] |
| Fuera de rango temporal | 0 | Fecha ∉ [2017-01-01, 2022-12-31] |
| Sin día en la grilla | 0 | El día UTC no aparece en los NetCDF (gaps esporádicos) |
| Sin celdas válidas | 0 | Ese día la grilla está totalmente cubierta por nubes/tierra |

(Total enriquecidas: 11,541 / 11,580 = 99.66%.)

## Detalle por columna

### `LAT_GRILLA`, `LON_GRILLA`

Coordenadas en grados decimales (signo negativo en sur/oeste) de la celda de la **grilla compartida 1/24°** (≈4 km) más cercana al lance, donde tanto SST como CHL están presentes ese día.

La grilla canónica está definida en [utils/cmems_common.py](../utils/cmems_common.py):

- `TARGET_LAT`: 95 puntos, paso 1/24°, entre −29.0 y −25.0.
- `TARGET_LON`: 36 puntos, paso 1/24°, entre −72.0 y −70.0.

**Garantía**: estos valores son byte-idénticos a los de las columnas `latitude`/`longitude` en `data/sst_atacama_2017_2022.csv` y `data/chl_atacama_2017_2022.csv`. Un merge directo es válido:

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

### `DISTANCIA_KM_GRILLA`

Distancia aproximada del lance a la celda elegida, en kilómetros. Calculada en una proyección equirectangular local centrada en −27° (longitud escalada por `cos(−27°) ≈ 0.891`) y luego convertida a km con factor 111.32 km/°. El error vs. la distancia haversine real es <0.5% sobre el bbox de Atacama.

Distribución observada: media ≈ 2 km, mediana < 2 km, máximo ≈ 15 km. Sirve como **métrica de calidad del match**: distancias altas pueden indicar cobertura nubosa intensa que día (la celda más cercana con datos quedó lejos del lance real). Para análisis estrictos puede ser útil filtrar `DISTANCIA_KM_GRILLA > 10` y dejar esos casos como NaN.

### `analysed_sst_celsius`

Sea Surface Temperature en grados Celsius en la celda matched, ese día UTC. Producto upstream: Copernicus L4 reprocesado `METOFFICE-GLO-SST-L4-REP-OBS-SST` (analizado, gap-free, diario, ~5 km nativos regrilados a 1/24° vía bilineal — ver [downloads/download_sst.py](../downloads/download_sst.py)).

El nombre se mantiene idéntico al del CSV upstream para permitir merges sin renombres.

### `chl_mg_m3`

Clorofila-a superficial en mg/m³ en la celda matched, ese día UTC. Producto upstream: Copernicus L4 multi-sensor gap-free `cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D` (ya nativo a 4 km / 1/24°, sin regrillado — ver [downloads/download_chl.py](../downloads/download_chl.py)).

Aunque el producto es "gap-free", queda NaN sobre tierra y en outages raros del sensor. La distribución es muy asimétrica (mucho rango bajo + cola larga durante eventos de surgencia).

## Cómo se computa el match

Pseudocódigo del algoritmo (implementación real en [enrich/enrich_ships.py](../enrich/enrich_ships.py)):

```
1. Cargar SST y CHL desde los .nc, convertir SST K→°C, fusionar en un Dataset.
2. Para cada lance, marcar como inelegible si:
     - LATITUD_DD o LONGITUD_DD es NaN
     - FECHA_HORA_ZARPE_UTC es NaN
     - (lat, lon) cae fuera del bbox de la grilla
     - fecha cae fuera de [2017-01-01, 2022-12-31]
3. Para cada fecha única (entre los lances elegibles):
     a. Slice del Dataset al día (ds.sel(time=fecha))
     b. Mascara las celdas con AMBAS variables no-nulas
     c. Si no quedan celdas → marcar todos los lances de ese día con NaN
     d. Construir cKDTree sobre las celdas válidas en proyección
        equirectangular local (lon * cos(-27°), lat)
     e. Query vectorizada con todos los lances del día → para cada lance,
        índice de celda más cercana + distancia
     f. Asignar LAT_GRILLA, LON_GRILLA, DISTANCIA_KM_GRILLA, SST, CHL
4. Escribir ships_enriched.csv (sep=";").
```

## Columnas heredadas relevantes para el match

Estas tres columnas ya existían en `ships_filtered.csv` y son las que determinan el resultado del enriquecimiento:

| Columna | Tipo | Origen | Rol |
|---|---|---|---|
| `LATITUD_DD` | float64, grados decimales | [filter_ships.py:dms_serie_a_decimal](../filters/filter_ships.py) sobre `LATITUD` (DMS empacado) | Entrada espacial al KDTree |
| `LONGITUD_DD` | float64, grados decimales | [filter_ships.py:dms_serie_a_decimal](../filters/filter_ships.py) sobre `LONGITUD` (DMS empacado) | Entrada espacial al KDTree |
| `FECHA_HORA_ZARPE_UTC` | string `YYYY-MM-DD` | [filter_ships.py:fecha_zarpe_a_utc_date](../filters/filter_ships.py) sobre `FECHA_HORA_ZARPE` (hora local Chile) | Slice temporal de SST/CHL |

Las columnas SERNAPESCA originales (`BARCO`, `FECHA_HORA_ZARPE`, `LATITUD`, `LONGITUD`, `ESPECIE`, `CAPTURA`, etc.) se preservan sin modificar.

## Reproducir

```bash
docker compose run --rm filter_ships    # ships.csv → ships_filtered.csv
docker compose run --rm enrich_ships    # ships_filtered.csv → ships_enriched.csv
```

Requiere que existan previamente:

- `data/ships.csv` (insumo SERNAPESCA)
- `data/sst_atacama_2017_2022.nc` (de `download_sst`)
- `data/chl_atacama_2017_2022.nc` (de `download_chl`)
