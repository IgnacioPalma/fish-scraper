# Diccionario de datos — `zarpes_atacama_haul_single.csv`

Subconjunto LIMPIO de `zarpes_atacama_haul_location.csv` para el modelado, en
`data/output/zarpes_atacama_haul_single.csv`. Generado por
`processing/locations/single_haul/filter_single_haul.py` (última etapa del pipeline
de localizaciones, posterior a `fishing_location`). Delimitador: `,`. Codificación: UTF-8.

Una fila por zarpe, con las **mismas columnas** que `zarpes_atacama_haul_location.csv`
(ver `zarpes_atacama_haul_location_diccionario.md`), recortado a los zarpes con un
**único lance confiable**:

- `haul_confidence == "alta"` — el lance representativo es un anillo circular del
  cerco (no un mero tramo lento mar adentro).
- `n_hauls == 1` — el viaje tiene exactamente un lance confiable.

Con ambas condiciones, la captura del viaje (`jack_mackerel_kg`, por zarpe) se mapea
sin ambigüedad a una única ubicación de pesca de alta confianza — el conjunto
apropiado para modelar captura ~ ambiente sin la ambigüedad de los viajes multi-lance.

Sucede al antiguo filtro `single_haul` que cruzaba el `num_hauls` declarado por IFOP;
ahora el nº de lances se deriva de la propia traza VMS (geometría circular en
`identify_fishing_location.py`), no de la bitácora.
