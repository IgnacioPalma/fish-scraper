# Diccionario de datos — `zarpes_atacama_capture.csv`

Producto final del pipeline de captura, en `data/output/zarpes_atacama_capture.csv`.
Generado por `processing/capture/unify/unify_zarpes.py`. Delimitador: `,`.
Codificación: UTF-8.

Une los zarpes de referencia de IFOP (`data/processing/ifop/zarpes_atacama.csv`)
con la captura filtrada de la bitácora (`data/processing/capture/capture.csv`)
mediante un **INNER JOIN** por `vessel_code` + la marca de tiempo de recalada
(`arrival_datetime` ↔ `landing_datetime`) a resolución de minuto. Cada fila es un
zarpe observado que además tiene captura de jurel registrada en la bitácora; los
zarpes sin captura quedan fuera (la captura está acotada a Caldera + jurel + rango
de fechas del estudio). El puente embarcación es la identidad
`COD_BARCO = HEX(vessel_code + 5)` (ver `data/bitacora/ifop_cod_barco_README.md`).

---

## Columnas

### Del zarpe (IFOP — `zarpes_atacama.csv`)

| Columna | Tipo | Descripción |
|---|---|---|
| `zarpe_id` | Entero | Identificador correlativo del zarpe en `zarpes_atacama.csv`. Llave para cruzar con las trazas VMS del pipeline de localizaciones. |
| `departure_datetime` | Fecha/hora | Fecha y hora de zarpe (salida a pesca), ISO 8601. |
| `arrival_datetime` | Fecha/hora | Fecha y hora de recalada, ISO 8601. Coincide al minuto con `landing_datetime`. |
| `vessel_code` | Texto | "Cód. Barco" decimal interno de IFOP (`id_interno`). Llave del cruce con la captura. |
| `departure_port_id` | Texto | Código de puerto de zarpe (→ `data/processing/ifop/ports.csv`). |
| `arrival_port_id` | Texto | Código de puerto de recalada (→ `ports.csv`). |
| `target_species_id` | Texto | Código de especie objetivo declarada en la ficha de detalle IFOP (puede venir vacío). |
| `num_hauls` | Entero | Número de lances del viaje. |

### De la embarcación (IFOP — `vessels.csv`)

| Columna | Tipo | Descripción |
|---|---|---|
| `vessel_name` | Texto | Nombre representativo de la embarcación para ese `vessel_code`. |

### De la captura (bitácora — `capture.csv`)

| Columna | Tipo | Descripción |
|---|---|---|
| `cod_barco` | Texto | `COD_BARCO` hexadecimal de la bitácora. Cumple `int(cod_barco, 16) − 5 == vessel_code`. |
| `landing_datetime` | Fecha/hora | Fecha y hora de recalada según la bitácora (`YYYY-MM-DD HH:MM:SS`). |
| `landing_port` | Texto | Puerto de desembarque de la bitácora. En este conjunto siempre `"Caldera"`. |
| `jack_mackerel_kg` | Decimal | Captura de jurel (*Trachurus murphyi*) declarada en el viaje, en kg (> 0). |
| `principal_catch` | Booleano | `True` si el jurel fue la especie con mayor captura del viaje. |
