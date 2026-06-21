# Diccionario de datos — `zarpes_atacama_haul_env.csv`

Producto final del [pipeline Copernicus](../../processing/copernicus/README.md). Una fila por zarpe de un solo
lance. Hereda todas las columnas de `zarpes_atacama_haul_location.csv` (identificación
del zarpe, captura y ubicación del lance) y agrega las covariables ambientales
muestreadas en el punto y día del lance + columnas de auditoría.

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
