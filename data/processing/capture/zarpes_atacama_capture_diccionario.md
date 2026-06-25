# Diccionario de datos — `zarpes_atacama_capture.csv`

Producto final del pipeline de captura, en `data/output/zarpes_atacama_capture.csv`.
Generado por `processing/capture/unify/unify_zarpes.py`. Delimitador: `,`.
Codificación: UTF-8.

La **espina es la bitácora**: cada fila es una recalada de jurel filtrada
(`data/processing/capture/capture.csv`, Caldera + jurel + rango del estudio,
captura > 0). Se le anexa `vessel_name` desde la tabla de embarcaciones de IFOP
(`data/processing/ifop/vessels.csv`) por un **LEFT JOIN** por `vessel_code`; las
recaladas de barcos ausentes del SIEM quedan con `vessel_name` nulo pero no se
descartan. El puente embarcación es la identidad `COD_BARCO = HEX(vessel_code + 5)`
(ver `data/bitacora/ifop_cod_barco_README.md`). La hora de zarpe y el nº de lances
ya no se incluyen: la ventana del viaje se reconstruye desde la traza VMS aguas
abajo (`identify_zarpes.py`).

---

## Columnas

| Columna | Tipo | Descripción |
|---|---|---|
| `zarpe_id` | Entero | Identificador correlativo (1..N) asignado en `unify_zarpes.py`. Llave para cruzar con las trazas VMS del pipeline de localizaciones. |
| `vessel_code` | Texto | "Cód. Barco" decimal interno de IFOP (`id_interno`). Llave del cruce con `vessels.csv`. |
| `vessel_name` | Texto | Nombre de la embarcación (IFOP `vessels.csv`). Nulo si el barco no está en el SIEM. |
| `cod_barco` | Texto | `COD_BARCO` hexadecimal de la bitácora. Cumple `int(cod_barco, 16) − 5 == vessel_code`. |
| `landing_datetime` | Fecha/hora | Fecha y hora de recalada según la bitácora (`YYYY-MM-DD HH:MM`). |
| `landing_port` | Texto | Puerto de desembarque de la bitácora. En este conjunto siempre `"Caldera"`. |
| `jack_mackerel_kg` | Decimal | Captura de jurel (*Trachurus murphyi*) declarada en el viaje, en kg (> 0). |
| `principal_catch` | Booleano | `True` si el jurel fue la especie con mayor captura del viaje. |
