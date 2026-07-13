"""
Une los CSVs diarios VMS de Sernapesca (uno por día, escritos por
processing.locations.scraper.download_locations) en un único CSV consolidado.

Lee data/processing/locations/raw_daily/flota_artesanal_YYYY-MM-DD.csv (relativo
a la raíz del proyecto) para todas las fechas disponibles, en orden cronológico
por nombre de archivo, y deduplica por (Radio Call Sign (RC), Location date).
Los reportes diarios de Sernapesca se solapan en los bordes —el archivo del día
N suele contener pings cuya "Location date" cae en el día N-1—, así que una
unión ingenua dejaría filas repetidas; este script las elimina manteniendo la
primera aparición (la del archivo cronológicamente anterior).

Procesamiento en STREAMING: en vez de cargar los ~cientos de CSV diarios en
memoria y concatenarlos (el dataset completo son decenas de millones de filas,
varios GB en RAM; un `pd.concat` + `sort` duplicaba ese pico y reventaba la
memoria del runner de CI), se recorre archivo por archivo y se anexan las filas
nuevas directo al CSV de salida. La memoria queda acotada por el set de claves
ya vistas (para deduplicar) más un único archivo diario a la vez, independiente
del total de filas. Como contrapartida, la salida queda ordenada por archivo
diario (cronológica a nivel de día, no estricta al segundo dentro de cada día);
los consumidores downstream (`clean_locations` y siguientes) no dependen del
orden exacto —recalculan tipos, filtran y reordenan según necesiten.

Esquema esperado: los 7 campos en inglés con BOM UTF-8. En la práctica,
Sernapesca cambió los encabezados en bloques enteros de días: un export
alternativo pero SEMÁNTICAMENTE IDÉNTICO usa `Mobile`/`Radio Call
Sign`/`Date`/`Speed` en vez de `Name`/`Radio Call Sign (RC)`/`Location
date`/`Speed (kt)`, y otro adjunta columnas extra al final (zonas UDA,
`Source`/`Modification date`). Esos alias se normalizan a los nombres
canónicos y las columnas extra se recortan, de modo que todos esos días se
consolidan. Sólo se saltan (con aviso en stderr) los archivos que ni siquiera
tras normalizar contienen las 7 columnas requeridas o que no son UTF-8
(encoding latin-1, esquema realmente distinto, etc.); esos días quedan sin
cubrir, pero el archivo diario crudo sigue disponible en disco.

Salida: data/processing/locations/raw_consolidated/locations_flota_artesanal_<rango>.csv,
con el mismo separador (`;`) y encoding UTF-8.

Idempotente: reescribe el archivo de salida en cada corrida.
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


# __file__ = processing/locations/consolidate/consolidate_locations.py → parents[3] = raíz del proyecto.
_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
INPUT_DIR = _DATA_DIR / "raw_daily"
OUTPUT_DIR = _DATA_DIR / "raw_consolidated"

DEDUP_KEYS = ["Radio Call Sign (RC)", "Location date"]
DATE_COL = "Location date"
DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

REQUIRED_COLS = [
    "Name",
    "Radio Call Sign (RC)",
    "Location date",
    "Latitude",
    "Longitude",
    "Heading",
    "Speed (kt)",
]

# Encabezados alternativos que Sernapesca usó en bloques enteros de días,
# equivalentes columna a columna a REQUIRED_COLS. Se renombran a los nombres
# canónicos antes de validar el esquema. Incluye el export en inglés
# (`Mobile`/`Date`/...) y el export en español (`Nombre`/`Fecha de posición`/...).
# Nota: el `Speed` alternativo trae el número pelado (sin sufijo " kt"); el
# limpiador downstream quita ese sufijo con str.replace, que es un no-op si no
# está, así que ambos formatos son compatibles.
HEADER_ALIASES = {
    # export alternativo en inglés
    "Mobile": "Name",
    "Radio Call Sign": "Radio Call Sign (RC)",
    "Date": "Location date",
    "Speed": "Speed (kt)",
    # export en español
    "Nombre": "Name",
    "Señal de llamada": "Radio Call Sign (RC)",
    "Fecha de posición": "Location date",
    "Latitud": "Latitude",
    "Longitud": "Longitude",
    "Rumbo": "Heading",
    "Velocidad (kt)": "Speed (kt)",
}


def _normalize_schema(df: pd.DataFrame) -> pd.DataFrame | None:
    """Renombra alias conocidos a los nombres canónicos y, si tras eso el
    DataFrame contiene las 7 columnas requeridas, lo recorta y reordena a
    REQUIRED_COLS (descartando columnas extra como las zonas UDA o
    Source/Modification date). Devuelve None si falta alguna columna requerida.
    """
    renamed = df.rename(columns=HEADER_ALIASES)
    if set(REQUIRED_COLS).issubset(renamed.columns):
        return renamed[REQUIRED_COLS]
    return None


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    # Glob estrecho (cuatro dígitos guión dos dígitos guión dos dígitos): captura
    # solo los CSV diarios `flota_artesanal_YYYY-MM-DD.csv` de raw_daily.
    pattern = f"{FLEET_NAME}_????-??-??.csv"
    files = sorted(INPUT_DIR.glob(pattern))

    if not files:
        print(
            f"ERROR: no se encontraron CSVs diarios en {INPUT_DIR} "
            f"(patrón '{pattern}').\n"
            "       Corré primero `uv run python -m processing.locations.scraper.download_locations`.",
            file=sys.stderr,
        )
        sys.exit(2)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    years = list(range(START_DATE.year, END_DATE.year + 1))
    year_tag = f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"
    output_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{year_tag}.csv"

    print(
        f"Consolidando reportes diarios VMS de Sernapesca ({FLEET_NAME})\n"
        f"  Archivos a unir:  {len(files)}\n"
        f"  Directorio:       {INPUT_DIR}\n"
    )

    # dtype=str: en pandas ≥3 mapea al dtype de string respaldado por PyArrow
    # (texto contiguo, mucho más liviano en RAM que el object de Python) y
    # preserva la precisión de lat/lon y el formato original de `Location date`
    # y `Speed (kt)`. Si algún consumidor downstream necesita numéricos, castea.
    #
    # `seen` acumula las claves de deduplicado ya escritas; es la ÚNICA
    # estructura que crece con el total de filas (una str compacta por ping
    # único). Todo lo demás se procesa un archivo a la vez y se descarta.
    seen: set[str] = set()
    skipped: list[tuple[str, str]] = []  # (filename, motivo)
    n_consolidados = 0
    total_pre_dedup = 0
    n_fecha_invalida = 0
    filas_finales = 0

    with output_csv.open("w", encoding="utf-8", newline="") as fh:
        header_escrito = False
        for path in files:
            try:
                df = pd.read_csv(path, sep=";", dtype=str, encoding="utf-8")
            except UnicodeDecodeError as exc:
                skipped.append((path.name, f"no es UTF-8 ({exc.reason})"))
                continue

            normalized = _normalize_schema(df)
            if normalized is None:
                skipped.append(
                    (path.name, f"columnas no estándar: {list(df.columns)}")
                )
                continue

            n_consolidados += 1
            total_pre_dedup += len(normalized)

            # Dedup dentro del archivo (keep="first"), luego contra lo ya visto.
            normalized = normalized.drop_duplicates(subset=DEDUP_KEYS, keep="first")
            keys = (
                normalized[DEDUP_KEYS[0]].astype("string").fillna("")
                + "\x00"
                + normalized[DEDUP_KEYS[1]].astype("string").fillna("")
            ).tolist()
            keep = [k not in seen for k in keys]
            seen.update(k for k, mantener in zip(keys, keep, strict=True) if mantener)

            # dtype=bool es imprescindible: si `keep` viene vacío (archivo diario
            # sin filas tras normalizar), un Series vacío sin dtype no es booleano
            # y pandas lo interpretaría como selección de COLUMNAS, no de filas.
            survivors = normalized[pd.Series(keep, index=normalized.index, dtype=bool)]

            # Conteo de fechas no parseables (no se descartan, solo se informan).
            dt = pd.to_datetime(
                survivors[DATE_COL], format=DATE_FORMAT, errors="coerce"
            )
            n_fecha_invalida += int(dt.isna().sum())

            survivors.to_csv(fh, sep=";", index=False, header=not header_escrito)
            header_escrito = True
            filas_finales += len(survivors)

    if skipped:
        print(
            f"Aviso: se saltaron {len(skipped)} archivo(s) con esquema no estándar:",
            file=sys.stderr,
        )
        for name, motivo in skipped:
            print(f"  - {name}: {motivo}", file=sys.stderr)

    if n_consolidados == 0:
        # Nada se escribió: el archivo quedó vacío; lo borramos para no dejar un
        # CSV sin encabezado que confunda al paso siguiente.
        output_csv.unlink(missing_ok=True)
        print(
            "ERROR: ningún archivo cumplió el esquema esperado "
            f"({REQUIRED_COLS}). Nada que consolidar.",
            file=sys.stderr,
        )
        sys.exit(2)

    # total_pre_dedup - filas_finales captura TODOS los duplicados eliminados
    # (intra-archivo + cross-archivo), sin depender del acumulador parcial.
    n_dup_eliminadas = total_pre_dedup - filas_finales

    size_mb = output_csv.stat().st_size / (1024 * 1024)
    print(
        f"Archivos encontrados:            {len(files):,}\n"
        f"Archivos saltados:               {len(skipped):,} "
        f"(esquema no estándar)\n"
        f"Archivos consolidados:           {n_consolidados:,}\n"
        f"Filas totales (pre-dedupe):      {total_pre_dedup:,}\n"
        f"Filas eliminadas por duplicado:  {n_dup_eliminadas:,} "
        f"(misma {DEDUP_KEYS[0]} y {DEDUP_KEYS[1]})\n"
        f"Filas con fecha inválida:        {n_fecha_invalida:,} "
        f"({DATE_COL} no parseable como {DATE_FORMAT})\n"
        f"Filas finales:                   {filas_finales:,}\n"
        f"Archivo escrito:                 {output_csv}\n"
        f"Tamaño:                          {size_mb:.1f} MB"
    )


if __name__ == "__main__":
    main()
