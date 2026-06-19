"""
Une los CSVs diarios VMS de Sernapesca (uno por día, escritos por
processing.locations.download_locations) en un único CSV consolidado.

Lee data/locations/flota_artesanal_YYYY-MM-DD.csv (relativo a la raíz del proyecto) para todas las fechas
disponibles, concatena en orden cronológico y deduplica por
(Radio Call Sign (RC), Location date). Los reportes diarios de Sernapesca se
solapan en los bordes —el archivo del día N suele contener pings cuya
"Location date" cae en el día N-1—, así que un concat ingenuo dejaría filas
repetidas; este script las elimina manteniendo la primera aparición.

Esquema esperado: los 7 campos en inglés con BOM UTF-8. En la práctica,
algunos días aislados Sernapesca subió un export distinto (columnas en
español, otra cantidad de columnas, coordenadas en grados-minutos-segundos,
encoding latin-1, etc.). Esos archivos se detectan por encoding o columnas
fuera de REQUIRED_COLS y se saltan con un aviso en stderr — el día queda
sin cubrir en el CSV consolidado, pero el archivo diario crudo sigue
disponible en disco si en el futuro se decide normalizarlo a mano.

Salida: data/locations/locations_flota_artesanal_<rango>.csv, con el
mismo separador (`;`) y encoding UTF-8.

Idempotente: reescribe el archivo de salida en cada corrida.
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


INPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "locations"
OUTPUT_DIR = INPUT_DIR

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


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    # Glob estrecho (cuatro dígitos guión dos dígitos guión dos dígitos): así
    # nunca capturamos el propio archivo de salida `locations_flota_artesanal_*.csv`.
    pattern = f"{FLEET_NAME}_????-??-??.csv"
    files = sorted(INPUT_DIR.glob(pattern))

    if not files:
        print(
            f"ERROR: no se encontraron CSVs diarios en {INPUT_DIR} "
            f"(patrón '{pattern}').\n"
            "       Corré primero `docker compose run --rm download_locations`.",
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

        if list(df.columns) != REQUIRED_COLS:
            skipped.append(
                (path.name, f"columnas no estándar: {list(df.columns)}")
            )
            continue

        dfs.append(df)

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
