"""
Une los CSVs diarios VMS de Sernapesca (uno por día, escritos por
processing.locations.scraper.download_locations) en un único CSV consolidado.

Lee data/processing/locations/raw_daily/flota_artesanal_YYYY-MM-DD.csv (relativo
a la raíz del proyecto) para todas las fechas
disponibles, concatena en orden cronológico y deduplica por
(Radio Call Sign (RC), Location date). Los reportes diarios de Sernapesca se
solapan en los bordes —el archivo del día N suele contener pings cuya
"Location date" cae en el día N-1—, así que un concat ingenuo dejaría filas
repetidas; este script las elimina manteniendo la primera aparición.

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

    print(
        f"Consolidando reportes diarios VMS de Sernapesca ({FLEET_NAME})\n"
        f"  Archivos a unir:  {len(files)}\n"
        f"  Directorio:       {INPUT_DIR}\n"
    )

    # dtype=str preserva la precisión de lat/lon y el formato original de
    # `Location date` y `Speed (kt)` (este último incluye sufijo ' kt'). Si
    # algún consumidor downstream necesita tipos numéricos, los castea él.
    dfs: list[pd.DataFrame] = []
    skipped: list[tuple[str, str]] = []  # (filename, motivo)
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

        dfs.append(normalized)

    if skipped:
        print(
            f"Aviso: se saltaron {len(skipped)} archivo(s) con esquema no estándar:",
            file=sys.stderr,
        )
        for name, motivo in skipped:
            print(f"  - {name}: {motivo}", file=sys.stderr)

    if not dfs:
        print(
            "ERROR: ningún archivo cumplió el esquema esperado "
            f"({REQUIRED_COLS}). Nada que consolidar.",
            file=sys.stderr,
        )
        sys.exit(2)

    combined = pd.concat(dfs, ignore_index=True)
    total_pre_dedup = len(combined)

    deduped = combined.drop_duplicates(subset=DEDUP_KEYS, keep="first")
    n_dup_eliminadas = total_pre_dedup - len(deduped)

    deduped = deduped.copy()
    deduped["_dt"] = pd.to_datetime(
        deduped[DATE_COL], format=DATE_FORMAT, errors="coerce"
    )
    n_fecha_invalida = int(deduped["_dt"].isna().sum())
    # NaT al final por defecto en sort_values: las filas con fecha no
    # parseable quedan al final, pero no se descartan.
    deduped = deduped.sort_values("_dt", kind="stable").drop(columns="_dt")

    years = list(range(START_DATE.year, END_DATE.year + 1))
    year_tag = f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"
    output_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{year_tag}.csv"

    deduped.to_csv(output_csv, sep=";", index=False, encoding="utf-8")

    size_mb = output_csv.stat().st_size / (1024 * 1024)
    print(
        f"Archivos encontrados:            {len(files):,}\n"
        f"Archivos saltados:               {len(skipped):,} "
        f"(esquema no estándar)\n"
        f"Archivos consolidados:           {len(dfs):,}\n"
        f"Filas totales (pre-dedupe):      {total_pre_dedup:,}\n"
        f"Filas eliminadas por duplicado:  {n_dup_eliminadas:,} "
        f"(misma {DEDUP_KEYS[0]} y {DEDUP_KEYS[1]})\n"
        f"Filas con fecha inválida:        {n_fecha_invalida:,} "
        f"({DATE_COL} no parseable como {DATE_FORMAT})\n"
        f"Filas finales:                   {len(deduped):,}\n"
        f"Archivo escrito:                 {output_csv}\n"
        f"Tamaño:                          {size_mb:.1f} MB"
    )


if __name__ == "__main__":
    main()
