# Diccionario de datos — `bitacora_caldera_jurel.csv`

Archivo generado por `processing/bitacora/filter_bitacora.py` a partir de
`bitacora_full.csv`. Delimitador: `;`. Codificación: UTF-8.

**Filtros aplicados**

| Filtro | Valor |
|---|---|
| Rango de fechas | Definido en `processing/utils/date_ranges.py` (`START_DATE`–`END_DATE`) |
| Puerto | `processing/utils/ports.py` → `PORT_OF_INTEREST` ("Caldera") |
| Especie | `processing/utils/species.py` → `SPECIES_OF_INTEREST` ("JACK_MACKEREL"), solo viajes con captura > 0 |

---

## Columnas

| Columna | Tipo | Descripción |
|---|---|---|
| `YEAR` | Entero | Año del viaje de pesca, extraído de la fecha de recalada. |
| `REGION` | Entero | Código numérico de la región administrativa de Chile. En este conjunto siempre es `3` (Región de Atacama). |
| `RPA` | Entero | Registro de Pesca Artesanal: identificador único de la embarcación. Convertido desde el campo original `COD_BARCO` (hexadecimal) a decimal por `clean_bitacora.py`. |
| `LANDING_DATETIME` | Fecha/hora | Fecha y hora de recalada en formato `YYYY-MM-DD HH:MM:SS`. Fuente: campo `FECHA_HORA_RECALADA` del original IFOP, normalizado desde formato americano `M/D/YYYY HH:MM`. |
| `PORT` | Texto | Puerto de desembarque asignado al puerto más cercano según las coordenadas del viaje (ver `puertos_atacama.json`). En este conjunto siempre es `"Caldera"`. |
| `JACK_MACKEREL` | Decimal | Captura de jurel (*Trachurus murphyi*) declarada en el viaje, en kg. Solo incluye viajes con captura > 0. Corresponde al campo original `JUREL` de la bitácora IFOP. |
| `PRINCIPAL_CATCH` | Booleano | `True` si el jurel fue la especie con mayor captura en el viaje (comparado contra todas las especies registradas en `bitacora_full.csv`); `False` en caso contrario. En caso de empate con otra especie, se considera `True`. |
