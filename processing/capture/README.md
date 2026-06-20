# Pipeline de captura (vessel capture)

Normaliza la bitácora IFOP cruda (registros de captura por recalada), la reduce a
las recaladas de jurel en Caldera dentro del rango de fechas del proyecto, y la
une con los zarpes de referencia de IFOP para dejar un dataset final por zarpe
enriquecido con su captura. Es el sucesor del antiguo pipeline `processing/bitacora`
(etapas de limpieza y filtrado); el emparejamiento VMS y el cruce de
nombres↔COD_BARCO siguen viviendo en `processing/bitacora` y consumen las salidas
de aquí.

> La etapa 3 (unificación) depende del pipeline IFOP: necesita
> `data/processing/ifop/zarpes_atacama.csv` y `vessels.csv`. Generalos antes con
> `uv run python -m processing.ifop.run_pipeline`.

## Ejecutar el pipeline completo

```bash
uv run python -m processing.capture.run_pipeline
```

Cada etapa también se puede correr por separado (en orden):

```bash
uv run python -m processing.capture.cleaning.clean_capture   # → cleaned/capture.csv
uv run python -m processing.capture.filter.filter_capture    # → capture.csv
uv run python -m processing.capture.unify.unify_zarpes        # → data/output/zarpes_atacama_capture.csv
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
| 3 | `unify.unify_zarpes` | `capture.csv` + `zarpes_atacama.csv` + `vessels.csv` | `data/output/zarpes_atacama_capture.csv` |

### 1. Limpieza — `processing/capture/cleaning/`

`clean_capture.py` normaliza la bitácora cruda: conserva `COD_BARCO` (código
hexadecimal de la bitácora IFOP) y deriva `vessel_code` = `int(COD_BARCO, 16) − 5`
(el "Cód. Barco" decimal interno de IFOP, inversa de la fórmula de
`processing/ifop/identifiers/extract_vessels.py`; ver
[data/bitacora/ifop_cod_barco_README.md](../../data/bitacora/ifop_cod_barco_README.md)).
Convierte `LATITUD`/`LONGITUD` (DDMMSS) a grados decimales y les asigna el puerto
más cercano de [cleaning/puertos_atacama.json](cleaning/puertos_atacama.json)
(columna `PORT`), pasa `FECHA_HORA_RECALADA` a ISO 8601 (`LANDING_DATETIME`),
renombra las columnas al inglés y descarta filas sin región. Cubre todos los años
disponibles (2012-2024); el recorte temporal lo hace la etapa de filtrado.

### 2. Filtrado — `processing/capture/filter/`

`filter_capture.py` recorta las recaladas al rango de fechas global del proyecto
([utils/date_ranges.py](../utils/date_ranges.py)), al puerto de interés
([utils/ports.py](../utils/ports.py), `Caldera`) y a la especie de interés
([utils/species.py](../utils/species.py), `JACK_MACKEREL`), reteniendo solo las
recaladas con captura positiva de jurel. Añade `PRINCIPAL_CATCH` (jurel fue la
especie más capturada del viaje) y elimina las columnas de las demás especies.

### 3. Unificación — `processing/capture/unify/`

`unify_zarpes.py` une los zarpes de referencia de IFOP
(`data/processing/ifop/zarpes_atacama.csv`, una fila por viaje observado) con la
captura filtrada (`capture.csv`), dejando un dataset por zarpe enriquecido con su
captura de jurel. El puente es la identidad `COD_BARCO = HEX(vessel_code + 5)`:
como la etapa de limpieza ya dejó `vessel_code` en la captura, el cruce es por
`vessel_code` + la marca de tiempo de recalada (`arrival_datetime` ↔
`landing_datetime`) a resolución de minuto. Es un **INNER JOIN**: solo quedan los
zarpes con captura (~70 de 562; el resto de los zarpes queda fuera porque la
captura está acotada a Caldera + jurel + rango de fechas del estudio). El cruce es
exacto cuando existe, así que ampliar la tolerancia (`TOL_MIN`) no agrega
coincidencias. Anexa `vessel_name` desde `vessels.csv`. Salida:
`data/output/zarpes_atacama_capture.csv` (producto final del proyecto).

## Consumidores aguas abajo

Las salidas de este pipeline las consumen, en `processing/bitacora`:

- `match_ifop_names.py` lee `cleaned/capture.csv` para construir el lookup
  nombre↔COD_BARCO desde el SIEM IFOP.
- `match_landings.py` lee `capture.csv` (el producto final) para emparejar cada
  recalada con la embarcación VMS más probable.
