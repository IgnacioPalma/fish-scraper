# Diccionario de datos — `zarpes_atacama_haul_location.csv`

Producto final del pipeline de localizaciones, en `data/output/zarpes_atacama_haul_location.csv`.
Generado por `processing/locations/fishing_location/identify_fishing_location.py`
(última etapa de la cadena `scraper → consolidate → cleaning → filter → zarpes →
fishing_location`). Delimitador: `,`. Codificación: UTF-8.

Una fila por zarpe (recalada de jurel con traza VMS asignada). A partir de la traza VMS
del viaje identifica el LUGAR donde la embarcación de cerco caló la red: clasifica
cada ping por velocidad (candidatos = mar adentro y a velocidad de pesca `0.3–4 kt`),
segmenta los candidatos en bouts temporales, y mide la GEOMETRÍA CIRCULAR de cada bout
con dos señales robustas a la cadencia del VMS: el **giro neto** `|Σ Δrumbo|` (un lance
cierra ~±360°) y la **compacidad** = largo de la traza / diagonal del bbox (un círculo
≈ 2.2, una recta ≈ 1). Un bout es un lance confiable (`is_set`) si es un anillo nítido
(compacidad ≥ 1.6) o un anillo parcial (giro neto ≥ 160° con compacidad ≥ 1.2, lo que
descarta el zigzag recto). El lance representativo del zarpe es el bout más "anillo"
(mayor compacidad); se reporta el centroide de sus pings como la ubicación del lance.
La captura de jurel (`jack_mackerel_kg`) se anexa cruzando por `zarpe_id` contra
`data/output/zarpes_atacama_capture.csv`.

Para no perder zarpes con captura cuya traza no cierra un anillo nítido (cobertura VMS
gruesa), los que tienen actividad lenta mar adentro pero ninguna geometría circular se
reportan igual, con `haul_confidence = "baja"` y `n_hauls = 0`; los que sí tienen un
anillo van con `haul_confidence = "alta"`. Solo los zarpes sin NINGÚN tramo lento mar
adentro quedan sin ubicación (`haul_confidence = "sin_pesca"`, columnas vacías). La
traza de pings etiquetada que respalda esta tabla (con `behavior` por ping, `is_haul`
y `haul_index` del lance) queda como artefacto auditable en
`data/processing/locations/fishing_location/locations_flota_artesanal_<rango>_fishing.csv`.

> **Nota de robustez.** Este detector heurístico (geometría de la maniobra) es el primer
> escalón. La desambiguación real de *lance* vs *búsqueda/deriva* y la incertidumbre de
> la ubicación corresponden a un modelo de estados de movimiento (HMM bayesiano sobre
> velocidad + ángulo de giro), trabajo posterior. Por eso conviene FILTRAR por
> `haul_confidence == "alta"` para los análisis que exijan ubicación de calidad.

---

## Columnas

### Identidad del zarpe y captura

| Columna | Tipo | Descripción |
|---|---|---|
| `zarpe_id` | Entero | Identificador del zarpe; misma llave que `zarpes_atacama_capture.csv` y la traza VMS. |
| `vessel_code` | Texto | "Cód. Barco" decimal interno de IFOP (`id_interno`). |
| `vessel_name` | Texto | Nombre representativo de la embarcación. |
| `jack_mackerel_kg` | Decimal | Captura de jurel del viaje, anexada desde `zarpes_atacama_capture.csv`. |
| `n_hauls` | Entero | Nº de lances CONFIABLES (anillos circulares) detectados en el viaje; 0 si la ubicación es de baja confianza. |
| `haul_confidence` | Texto | `alta` (lance representativo es un anillo circular), `baja` (solo tramo lento mar adentro, sin anillo) o `sin_pesca` (sin tramo lento mar adentro; sin ubicación). |

### Ubicación del lance (vacías solo si `haul_confidence == "sin_pesca"`)

| Columna | Tipo | Descripción |
|---|---|---|
| `haul_lat` | Decimal | Latitud del centroide del bout representativo (lugar del lance). |
| `haul_lon` | Decimal | Longitud del centroide del bout representativo. |
| `haul_start` | Fecha/hora | Inicio del bout representativo (`YYYY-MM-DD HH:MM:SS`). |
| `haul_end` | Fecha/hora | Fin del bout representativo. |
| `haul_duration_h` | Decimal | Duración del bout representativo, en horas. |
| `haul_n_pings` | Entero | Nº de pings VMS que componen el bout representativo. |
| `haul_mean_speed_kt` | Decimal | Velocidad media (kt) durante el bout. |
| `haul_net_turn_deg` | Decimal | Giro neto `|Σ Δrumbo|` (grados) del bout representativo; ~360° en un anillo cerrado. |
| `haul_compactness` | Decimal | Compacidad (largo de traza / diagonal del bbox) del bout; círculo ≈ 2.2, recta ≈ 1. |
| `haul_dist_port_km` | Decimal | Distancia (km) del centroide del lance al puerto más cercano. |
| `nearest_port` | Texto | Puerto más cercano al centroide del lance. |
