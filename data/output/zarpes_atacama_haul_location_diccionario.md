# Diccionario de datos — `zarpes_atacama_haul_location.csv`

Producto final del pipeline de localizaciones, en `data/output/zarpes_atacama_haul_location.csv`.
Generado por `processing/locations/fishing_location/identify_fishing_location.py`
(última etapa de la cadena `scraper → consolidate → cleaning → filter → zarpes →
single_haul → fishing_location`). Delimitador: `,`. Codificación: UTF-8.

Una fila por zarpe de un solo lance (`num_hauls == 1`). A partir de la traza VMS
del viaje identifica el LUGAR donde la embarcación de cerco caló la red: clasifica
cada ping por velocidad + rumbo (candidatos = mar adentro y a velocidad de pesca
`0.3–4 kt`), segmenta los candidatos en bouts temporales, elige el bout dominante
por giro acumulado (exigiendo giro medio ≥ 20° — el cerco circula al calar, lo que
descarta la deriva recta), y reporta el centroide de ese bout como la ubicación del
lance. La captura de jurel (`jack_mackerel_kg`) se anexa cruzando por `zarpe_id`
contra `data/output/zarpes_atacama_capture.csv`.

Los zarpes cuya traza VMS no contiene comportamiento de pesca (cobertura escasa: el
barco solo reporta en tránsito) se conservan con la captura pero con las columnas de
ubicación del lance vacías. La traza de pings etiquetada que respalda esta tabla
(con `behavior` por ping e `is_haul`) queda como artefacto auditable en
`data/processing/locations/fishing_location/locations_flota_artesanal_<rango>_fishing.csv`.

---

## Columnas

### Identidad del zarpe y captura

| Columna | Tipo | Descripción |
|---|---|---|
| `zarpe_id` | Entero | Identificador del zarpe; misma llave que `zarpes_atacama_capture.csv` y la traza VMS. |
| `vessel_code` | Texto | "Cód. Barco" decimal interno de IFOP (`id_interno`). |
| `vessel_name` | Texto | Nombre representativo de la embarcación. |
| `jack_mackerel_kg` | Decimal | Captura de jurel del viaje, anexada desde `zarpes_atacama_capture.csv`. |

### Ubicación del lance (vacías si no se detectó pesca)

| Columna | Tipo | Descripción |
|---|---|---|
| `haul_lat` | Decimal | Latitud del centroide del bout de pesca dominante (lugar del lance). |
| `haul_lon` | Decimal | Longitud del centroide del bout de pesca dominante. |
| `haul_start` | Fecha/hora | Inicio del bout de pesca (`YYYY-MM-DD HH:MM:SS`). |
| `haul_end` | Fecha/hora | Fin del bout de pesca. |
| `haul_duration_h` | Decimal | Duración del bout de pesca, en horas. |
| `haul_n_pings` | Entero | Nº de pings VMS que componen el bout de pesca. |
| `haul_mean_speed_kt` | Decimal | Velocidad media (kt) durante el bout. |
| `haul_dist_port_km` | Decimal | Distancia (km) del centroide del lance al puerto más cercano. |
| `nearest_port` | Texto | Puerto más cercano al centroide del lance. |
