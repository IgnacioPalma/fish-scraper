# Diccionario de datos — `zarpes_atacama_haul_env.csv`

Producto final del [pipeline Copernicus](../../processing/copernicus/README.md) y dataset de
modelado. Una fila por zarpe de un único lance confiable. Hereda todas las columnas de
`zarpes_atacama_haul_single.csv` (identificación del zarpe, captura, `principal_catch` y
ubicación del lance) y agrega las covariables ambientales muestreadas en el punto y día
del lance + columnas de auditoría.

| Columna | Unidad | Descripción |
|---|---|---|
| `zarpe_id` | — | Identificador único del zarpe (viaje de pesca). |
| `vessel_code` | — | Código interno IFOP de la embarcación. |
| `vessel_name` | — | Nombre de la embarcación. |
| `jack_mackerel_tons` | tons | Captura de jurel del zarpe (variable respuesta del modelo). |
| `principal_catch` | booleano | `True` si el jurel fue la especie con mayor captura del viaje. |
| `n_hauls` | — | Nº de lances confiables del viaje. En este dataset siempre `1` (filtro de un único lance). |
| `haul_confidence` | — | Confianza de la ubicación. En este dataset siempre `alta` (anillo circular del cerco). |
| `haul_lat` | grados | Latitud del lance (centroide del bout de pesca). |
| `haul_lon` | grados | Longitud del lance. |
| `haul_start` | ISO 8601 | Inicio de la ventana del lance. |
| `haul_end` | ISO 8601 | Fin de la ventana del lance. |
| `haul_duration_h` | horas | Duración de la ventana del lance. |
| `haul_n_pings` | — | Nº de pings VMS en el bout de pesca. |
| `haul_mean_speed_kt` | nudos | Velocidad media de los pings del lance. |
| `haul_net_turn_deg` | grados | Giro neto `|Σ Δrumbo|` del bout; ~360° en un anillo cerrado del cerco. |
| `haul_compactness` | — | Compacidad (largo de traza / diagonal del bbox) del bout; círculo ≈ 2.2, recta ≈ 1. |
| `haul_dist_port_km` | km | Distancia del lance al puerto más cercano. |
| `nearest_port` | — | Puerto más cercano al lance. |
| **`sst_c`** | °C | Temperatura superficial del mar (SST) en el lance. |
| **`chl_mg_m3`** | mg/m³ | Clorofila-a superficial (productividad / alimento). |
| **`mld_m`** | m | Profundidad de la capa de mezcla (estructura vertical de la columna). |
| **`sss_psu`** | PSU | Salinidad superficial (discrimina masas de agua / frente subtropical). |
| **`o2_min_mmol_m3`** | mmol/m³ | Mínimo de O₂ disuelto en 0–200 m (techo de la OMZ; comprime el hábitat pelágico). |
| **`sst_front_c_per_km`** | °C/km | Magnitud del gradiente horizontal de SST \|∇SST\| (intensidad del frente térmico en el lance). |
| **`chl_front_mg_m3_per_km`** | (mg/m³)/km | Magnitud del gradiente horizontal de clorofila \|∇CHL\| (intensidad del frente de productividad). |
| **`wind_stress_pa`** | Pa (N/m²) | Módulo del esfuerzo del viento τ = ρ·C_d·\|U\|² (ρ=1.22 kg/m³, C_d=1.3e-3); forzante del afloramiento costero. |
| **`wind_stress_east_pa`** | Pa | Componente zonal (este +) del esfuerzo del viento. |
| **`wind_stress_north_pa`** | Pa | Componente meridional (norte +) del esfuerzo del viento; para derivar el componente along-shore/upwelling. |
| **`moon_illumination`** | — | Fracción iluminada del disco lunar en la fecha del lance (0 = luna nueva, 1 = luna llena); modula la captabilidad del cerco. |
| `env_time` | YYYY-MM-DD | Día de la grilla oceánica efectivamente muestreado (el más cercano al lance). |
| `env_cell_dist_km` | km | Distancia máxima a una celda oceánica muestreada; 0 si todas fueron la celda más cercana, > 0 si hubo fallback costero. |
| `env_status` | — | `ok` (todas exactas) · `fallback` (alguna usó la celda de mar más cercana) · `fuera_de_rango` (lance fuera de la cobertura temporal de las grillas oceánicas). El estado `sin_coords` no aparece aquí: todos los lances de este dataset tienen ubicación. Los frentes comparten estado con SST/CHL. |
| `wind_time` | YYYY-MM-DD | Día de la grilla de viento efectivamente muestreado (auditoría propia: el viento tiene cobertura temporal distinta a las capas oceánicas). |
| `wind_cell_dist_km` | km | Distancia máxima a una celda de viento muestreada; > 0 si hubo fallback costero. |
| `wind_status` | — | Estado del muestreo de viento (`ok` · `fallback` · `fuera_de_rango` · `sin_grilla`), análogo a `env_status`. Si la grilla de viento no cubre la fecha del lance, `wind_stress_*` queda nulo y `wind_status = fuera_de_rango`; si la capa de viento no se descargó aún, `wind_status = sin_grilla` (el resto de covariables no se ven afectadas). |

> **Nota sobre el O₂.** El producto biogeoquímico es de 0.25° (~25 km), la única
> resolución del reanálisis BGC. Su máscara de tierra gruesa empuja a varios lances
> costeros a tomar el O₂ de celdas mar adentro (hasta ~20 km); `env_cell_dist_km`
> registra ese desplazamiento por fila para poder filtrar o ponderar. SSS, MLD, SST y
> CHL muestrean su celda exacta salvo excepciones menores.

> **Nota sobre los frentes.** `sst_front_*` y `chl_front_*` son la magnitud del
> gradiente horizontal (\|∇\|) del campo, calculada por diferencias finitas sobre la
> grilla regridada (1/24° ≈ 4 km) y muestreada en la celda del lance. El gradiente en
> Kelvin es idéntico al gradiente en °C (el offset constante se cancela), por eso
> `sst_front` está en °C/km sin conversión. El borde tierra-mar hereda el NaN de la
> máscara, así que un lance pegado a la costa puede tomar el gradiente de la celda de
> mar más cercana (mismo fallback que las demás capas oceánicas).

> **Nota sobre el viento.** El esfuerzo del viento usa la fórmula bulk
> τ = ρ_air·C_d·\|U\|·U con ρ_air = 1.22 kg/m³ y C_d = 1.3e-3 constante (aproximación
> estándar a 10 m); `wind_stress_pa` es el módulo y `wind_stress_east/north_pa` sus
> componentes. El producto de viento (`wind_atacama_*`) tiene cobertura temporal
> propia — si no cubre el rango de los lances, hay que re-descargarlo con
> `uv run python -m processing.copernicus.download_wind --force`; mientras tanto los
> lances sin cobertura quedan con `wind_stress_*` nulo y `wind_status = fuera_de_rango`.

> **Nota sobre la fase lunar.** `moon_illumination` no se descarga: se deriva de la
> fecha del lance con el mes sinódico medio (error < ~0.02 en la fracción iluminada),
> suficiente como covariable de captabilidad.
