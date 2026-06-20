"""
Especie de interés del proyecto.

Fuente de verdad única para filtrar registros por especie objetivo.
El valor coincide con el nombre de columna en
data/processing/capture/cleaned/capture.csv tal como lo define
processing/capture/cleaning/clean_capture.py (COLUMN_RENAME).
Para cambiar la especie, editá solo esta constante.
"""

SPECIES_OF_INTEREST = "JACK_MACKEREL"

ALL_SPECIES = [
    "NEEDLEFISH",
    "ANCHOVY",
    "BLUE_WHITING",
    "BONITO",
    "MACKEREL",
    "CABINZA",
    "CORVINA",
    "SQUID",
    "JACK_MACKEREL",
    "MACHUELO",
    "JELLYFISH",
    "SILVERSIDE",
    "SARDINE",
]
