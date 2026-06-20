# Pipeline de captura (vessel capture)

Normaliza la bitácora IFOP cruda (registros de captura por recalada) y la
reduce a las recaladas de jurel en Caldera dentro del rango de fechas del
proyecto. Es el sucesor del antiguo pipeline `processing/bitacora` (etapas de
limpieza y filtrado); el emparejamiento VMS y el cruce de nombres↔COD_BARCO
siguen viviendo en `processing/bitacora` y consumen las salidas de aquí.

## Ejecutar el pipeline completo

```bash
uv run python -m processing.capture.run_pipeline
```

Cada etapa también se puede correr por separado (en orden):

```bash
uv run python -m processing.capture.cleaning.clean_capture   # → cleaned/capture.csv
uv run python -m processing.capture.filter.filter_capture    # → capture.csv
```

## Entrada

La bitácora IFOP cruda debe estar en:

```
data/processing/capture/input/bitacora.csv
```

## Etapas

| # | Módulo | Entrada | Salida |
|---|---|---|---|
| 1 | `cleaning.clean_capture` | `input/bitacora.csv` | `data/processing/capture/cleaned/capture.csv` |
| 2 | `filter.filter_capture` | `cleaned/capture.csv` | `data/processing/capture/capture.csv` |

### 1. Limpieza — `processing/capture/cleaning/`

`clean_capture.py` normaliza la bitácora cruda: conserva `COD_BARCO` (código
interno IFOP, no hex), convierte `LATITUD`/`LONGITUD` (DDMMSS) a grados
decimales y les asigna el puerto más cercano de
[cleaning/puertos_atacama.json](cleaning/puertos_atacama.json) (columna `PORT`),
pasa `FECHA_HORA_RECALADA` a ISO 8601 (`LANDING_DATETIME`), renombra las
columnas al inglés y descarta filas sin región. Cubre todos los años
disponibles (2012-2024); el recorte temporal lo hace la etapa de filtrado.

### 2. Filtrado — `processing/capture/filter/`

`filter_capture.py` recorta las recaladas al rango de fechas global del proyecto
([utils/date_ranges.py](../utils/date_ranges.py)), al puerto de interés
([utils/ports.py](../utils/ports.py), `Caldera`) y a la especie de interés
([utils/species.py](../utils/species.py), `JACK_MACKEREL`), reteniendo solo las
recaladas con captura positiva de jurel. Añade `PRINCIPAL_CATCH` (jurel fue la
especie más capturada del viaje) y elimina las columnas de las demás especies.

## Consumidores aguas abajo

Las salidas de este pipeline las consumen, en `processing/bitacora`:

- `match_ifop_names.py` lee `cleaned/capture.csv` para construir el lookup
  nombre↔COD_BARCO desde el SIEM IFOP.
- `match_landings.py` lee `capture.csv` (el producto final) para emparejar cada
  recalada con la embarcación VMS más probable.
