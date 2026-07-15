# Diccionario de datos — `zarpes_atacama_haul_single.csv`

Conjunto de MODELADO derivado de `zarpes_atacama_haul_location.csv`, en
`data/processing/locations/single_haul/zarpes_atacama_haul_single.csv`. Generado por
`processing/locations/single_haul/filter_single_haul.py` (última etapa del pipeline
de localizaciones, posterior a `fishing_location`). Delimitador: `,`. Codificación: UTF-8.

Una fila por zarpe, con las **mismas columnas** que `zarpes_atacama_haul_location.csv`
(ver `zarpes_atacama_haul_location_diccionario.md`) **más `sample_weight` e
`is_single_haul`**, conservando **todos los zarpes con ubicación de lance**:

> **Variante multiespecie (`SPECIES_SCOPE=all`).** Con `SPECIES_SCOPE=all` el
> archivo se genera bajo `…/all_species/single_haul/` y trae una columna
> `<especie>_tons` por especie en lugar de solo `jack_mackerel_tons`; el conjunto
> de zarpes es un superconjunto (recaladas de cerco con captura de cualquier
> especie). El resto del esquema es idéntico.


- Se CONSERVAN los `haul_confidence in {"alta", "baja"}` (los que tienen
  `haul_lat`/`haul_lon`).
- Se DESCARTAN solo los `haul_confidence == "sin_pesca"` (sin ningún tramo lento mar
  adentro → sin ubicación que muestrear).

Antes esta etapa recortaba al conjunto ESTRICTO (`alta` **y** `n_hauls == 1`), lo que
descartaba la mayoría de los zarpes localizados y dejaba muy pocos ejemplos para
entrenar (sobreajuste). Ahora se conservan todos los zarpes con ubicación y la calidad
se expone como columnas, para que el modelo decida cómo usarlos.

## Columnas agregadas

| Columna | Tipo | Descripción |
|---|---|---|
| `sample_weight` | Decimal | Peso por ejemplo según la confianza de la ubicación: `alta` → 1.0, `baja` → 0.5 (constantes `ALTA_WEIGHT`/`BAJA_WEIGHT` en `filter_single_haul.py`). Punto de partida **ajustable**; para un modelo de captura conviene además bajar el peso de los viajes multi-lance usando `n_hauls`. |
| `is_single_haul` | Booleano | `True` sii `haul_confidence == "alta"` **y** `n_hauls == 1`. Reproduce el antiguo conjunto ESTRICTO con un solo filtro — usalo si necesitás atribución inequívoca captura→ubicación (p. ej. un modelo de captura por zarpe). |

## Cómo usarlo

- **Modelo de presencia / idoneidad**: usar todas las filas; opcionalmente ponderar con
  `sample_weight`.
- **Modelo de captura (kg)**: la captura del zarpe (`jack_mackerel_kg`) se atribuye a la
  ubicación representativa; en viajes multi-lance eso es una aproximación. Filtrá por
  `is_single_haul` para el subconjunto sin ambigüedad, o mantené todo y bajá el peso de
  los multi-lance (p. ej. `sample_weight / n_hauls`).

Sucede al antiguo filtro `single_haul` que cruzaba el `num_hauls` declarado por IFOP;
ahora el nº de lances se deriva de la propia traza VMS (geometría circular en
`identify_fishing_location.py`), no de la bitácora.
