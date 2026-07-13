"""
Limpia el CSV consolidado de posiciones VMS de Sernapesca
(`consolidate_locations.py`) y deja una tabla lista para análisis con nombres
de columna en inglés, tipos numéricos y recortada al bounding box de Atacama.

Transformaciones (entrada → salida):

  Name                 → vessel_name        (texto, tal cual; el sufijo "(ART)"
                                              se conserva — normalizar el nombre
                                              es trabajo del paso de matching)
  Radio Call Sign (RC) → radio_call_sign    (texto)
  Location date        → location_datetime  (ISO 8601, desde dd/mm/aaaa HH:MM:SS)
  Latitude             → latitude           (float)
  Longitude            → longitude          (float)
  Heading              → heading            (float)
  Speed (kt)           → speed_kt           (float; se quita el sufijo " kt")

Filtrado espacial: se conservan solo los pings dentro del bounding box de
Atacama (LAT_MIN/LAT_MAX, LON_MIN/LON_MAX en processing/utils/cmems_common.py,
la fuente única de verdad del área de estudio). La flota artesanal reporta a lo
largo de todo Chile; este recorte deja únicamente la costa de Atacama.

Filas con latitud o longitud no numérica se descartan (no se pueden ubicar ni
filtrar). Las fechas no parseables se conservan con `location_datetime` vacío.

Entrada:
  data/processing/locations/raw_consolidated/locations_flota_artesanal_<rango>.csv

Salida:
  data/processing/locations/cleaned/locations_flota_artesanal_<rango>_cleaned.csv

El <rango> se deriva del rango global (processing/utils/date_ranges.py), igual
que en consolidate_locations.py, así la entrada apunta exactamente al archivo
que produjo el paso anterior.

Uso:
    uv run python -m processing.locations.cleaning.clean_locations
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.cmems_common import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
INPUT_DIR = DATA_DIR / "raw_consolidated"
OUTPUT_DIR = DATA_DIR / "cleaned"

# Formato de fecha del export Sernapesca (dd/mm/aaaa HH:MM:SS).
DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

# Filas por bloque al leer el consolidado (ver comentario en main): acota el
# pico de RAM sin fragmentar tanto como para volver lenta la escritura.
CHUNKSIZE = 2_000_000

# Renombrado de columnas: nombre crudo Sernapesca → nombre estándar en inglés.
RENAME = {
    "Name": "vessel_name",
    "Radio Call Sign (RC)": "radio_call_sign",
    "Location date": "location_datetime",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Heading": "heading",
    "Speed (kt)": "speed_kt",
}

# Orden final de columnas en la salida.
COLS_SALIDA = [
    "vessel_name",
    "radio_call_sign",
    "location_datetime",
    "latitude",
    "longitude",
    "heading",
    "speed_kt",
]


def _rango_tag() -> str:
    """Etiqueta de rango (`2023` o `2023_2024`), idéntica a consolidate_locations."""
    years = list(range(START_DATE.year, END_DATE.year + 1))
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"


def limpiar(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Renombra, tipa, recorta al bounding box y devuelve (tabla, estadísticas)."""
    out = df.rename(columns=RENAME)

    # Tipos numéricos. Algunos exports Sernapesca anexan sufijos al valor:
    # lat/lon con el símbolo de grado (p.ej. "-29.23520°") y la velocidad con
    # " kt" (p.ej. "0.00 kt"). Se quitan antes de convertir a número.
    #
    # dtype=float64 explícito: `pd.to_numeric` devuelve int64 si el bloque no
    # tiene NaN ni decimales y float64 si los tiene, así que sin el cast el
    # rumbo se escribiría como `355` en un chunk y `355.0` en otro (procesamos
    # por bloques, ver main). Fijar float hace la salida determinista e idéntica
    # a la de una lectura de una sola pasada.
    out["latitude"] = pd.to_numeric(
        out["latitude"].str.replace("°", "", regex=False).str.strip(),
        errors="coerce",
    ).astype("float64")
    out["longitude"] = pd.to_numeric(
        out["longitude"].str.replace("°", "", regex=False).str.strip(),
        errors="coerce",
    ).astype("float64")
    out["heading"] = pd.to_numeric(out["heading"], errors="coerce").astype("float64")
    out["speed_kt"] = pd.to_numeric(
        out["speed_kt"].str.replace("kt", "", regex=False).str.strip(),
        errors="coerce",
    ).astype("float64")

    # Fecha → ISO 8601; valores ilegibles quedan vacíos (NaT → "").
    dt = pd.to_datetime(out["location_datetime"], format=DATE_FORMAT, errors="coerce")
    n_fecha_invalida = int(dt.isna().sum())
    out["location_datetime"] = dt.dt.strftime("%Y-%m-%d %H:%M:%S")

    # Descartar pings sin coordenadas numéricas (no se pueden ubicar ni filtrar).
    sin_coords = out["latitude"].isna() | out["longitude"].isna()
    n_sin_coords = int(sin_coords.sum())
    out = out[~sin_coords]

    # Recorte espacial al bounding box de Atacama (inclusivo en ambos extremos).
    dentro = (
        out["latitude"].between(LAT_MIN, LAT_MAX)
        & out["longitude"].between(LON_MIN, LON_MAX)
    )
    n_fuera_bbox = int((~dentro).sum())
    out = out[dentro]

    stats = {
        "fecha_invalida": n_fecha_invalida,
        "sin_coords": n_sin_coords,
        "fuera_bbox": n_fuera_bbox,
    }
    return out[COLS_SALIDA], stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    input_csv = INPUT_DIR / f"locations_{FLEET_NAME}_{tag}.csv"
    output_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{tag}_cleaned.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no existe {input_csv}.\n"
            "       Generá el CSV consolidado primero con:\n"
            "           uv run python -m processing.locations.consolidate.consolidate_locations",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Limpiando posiciones VMS consolidadas ({FLEET_NAME})\n"
        f"  Entrada:      {input_csv}\n"
        f"  Bounding box: lat [{LAT_MIN}, {LAT_MAX}], lon [{LON_MIN}, {LON_MAX}]\n"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Lectura por CHUNKS: el consolidado completo son decenas de millones de
    # filas (varios GB) y cargarlo entero + las copias que genera `limpiar`
    # (str.replace, to_numeric, to_datetime, filtrado) reventaba la memoria del
    # runner de CI. La salida, en cambio, es chica: el recorte al bounding box
    # de la región descarta la enorme mayoría de los pings (la flota reporta en
    # toda la costa de Chile). Procesamos un bloque a la vez y anexamos las
    # filas ya recortadas al CSV de salida; el pico de RAM queda acotado al
    # tamaño de un chunk, independiente del total de filas.
    n_entrada = 0
    n_final = 0
    stats_total = {"fecha_invalida": 0, "sin_coords": 0, "fuera_bbox": 0}

    reader = pd.read_csv(
        input_csv, sep=";", dtype=str, encoding="utf-8", chunksize=CHUNKSIZE
    )
    primero = True
    with output_csv.open("w", encoding="utf-8", newline="") as fh:
        for chunk in reader:
            if primero:
                faltantes = [c for c in RENAME if c not in chunk.columns]
                if faltantes:
                    print(
                        f"ERROR: al CSV de entrada le faltan columnas esperadas: {faltantes}.\n"
                        "       ¿Cambió el esquema de consolidate_locations.py?",
                        file=sys.stderr,
                    )
                    sys.exit(1)

            n_entrada += len(chunk)
            limpio, stats = limpiar(chunk)
            for k in stats_total:
                stats_total[k] += stats[k]

            limpio.to_csv(fh, index=False, header=primero)
            n_final += len(limpio)
            primero = False

    size_mb = output_csv.stat().st_size / (1024 * 1024)
    print(
        f"Filas de entrada:                {n_entrada:,}\n"
        f"Descartadas sin coordenadas:     {stats_total['sin_coords']:,}\n"
        f"Descartadas fuera del bbox:      {stats_total['fuera_bbox']:,}\n"
        f"Fechas ilegibles (campo vacío):  {stats_total['fecha_invalida']:,}\n"
        f"Filas finales:                   {n_final:,}\n"
        f"Archivo escrito:                 {output_csv}\n"
        f"Tamaño:                          {size_mb:.1f} MB"
    )


if __name__ == "__main__":
    main()
