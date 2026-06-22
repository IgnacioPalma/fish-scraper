"""
Limpieza del registro histórico de embarcaciones (paso 1 del pipeline registry).

Lee data/processing/registry/raw/register.csv (registro nacional producido por la
etapa 0 `scraper`) y produce una versión limpia en
data/processing/registry/cleaned/register.csv. Operaciones:

  1. Renombra TODAS las columnas a inglés (Correlativo→id, Nº RPA→RPA,
     Nº Matrícula→registration_number, etc.).
  2. Normaliza la fecha de inscripción a ISO 8601 (DD-MM-YYYY → YYYY-MM-DD).
  3. Elimina columnas que no se usan aguas abajo (puerto, vencimiento de
     matrícula, tipo, RUT y nombre del armador, oficina).
  4. Deduplica: el registro histórico añade una fila cada vez que una
     embarcación cambia de armador (nuevo Nº RPA), pero la matrícula del puerto
     se mantiene. Para cada (Nº Matrícula, Puerto) se conserva la inscripción
     más reciente según `Fecha Inscripción`, de modo que el RPA exportado sea el
     que aparece en los reportes VMS de Sernapesca. La deduplicación usa `Puerto`
     (la matrícula sola no basta: el mismo número se reutiliza entre puertos),
     por eso ocurre ANTES de descartar esa columna.

El filtro por categoría (LANCHA) NO vive aquí: es un paso posterior en
processing/registry/filter.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_DIR = DATA_DIR / "processing" / "registry"
INPUT_CSV = REGISTRY_DIR / "raw" / "register.csv"
OUTPUT_CSV = REGISTRY_DIR / "cleaned" / "register.csv"

# Columnas originales (separador ';') → nombre en inglés. Solo las que se
# conservan; el resto se descarta. El orden define el orden de salida.
# `Region` (código romano, lo agrega el scraper nacional) se conserva para que la
# etapa region_filter pueda recortar al perfil de región activo.
RENAME = {
    "Correlativo": "id",
    "Nº RPA": "RPA",
    "Nombre Embarcación": "vessel_name",
    "Categoría": "category",
    "Fecha Inscripción": "registration_date",
    "Nº Matrícula": "registration_number",
    "Eslora": "length",
    "Manga": "beam",
    "Puntal": "depth",
    "T.R.G": "gross_tonnage",
    "Potencia": "engine_power",
    "Bodega": "hold_capacity",
    "Caleta": "cove",
    "Region": "region",
}

# Columnas a eliminar explícitamente. `Puerto` se usa para deduplicar antes de
# eliminarse, así que se descarta al final junto con el resto.
DROP_COLS = [
    "Puerto",
    "Venc. Matríc",
    "Tipo",
    "Rut Armador",
    "Nombre Armador",
    "Oficina",
]

# Claves de deduplicación (en nombres ORIGINALES, antes de renombrar/eliminar).
DEDUP_KEYS = ["Nº Matrícula", "Puerto"]
FECHA_COL = "Fecha Inscripción"


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Generá el registro nacional primero con:\n"
            "           uv run python -m processing.registry.scraper.scrape_registry",
            file=sys.stderr,
        )
        sys.exit(2)

    # El archivo usa ';' como separador (no ',').
    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, encoding="utf-8")

    requeridas = list(RENAME) + DROP_COLS
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {faltantes}.",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(df)

    # Fecha a datetime para deduplicar por la inscripción más reciente y para
    # exportarla en ISO 8601. Las fechas no parseables quedan como NaT (la fila
    # se conserva; su fecha sale vacía).
    fecha_dt = pd.to_datetime(df[FECHA_COL], format="%d-%m-%Y", errors="coerce")
    n_fecha_invalida = int(fecha_dt.isna().sum())

    # Deduplicación: ordenar por fecha descendente (NaT al final, para que una
    # fila con fecha válida gane sobre una sin fecha en la misma clave) y
    # conservar la primera de cada (Nº Matrícula, Puerto).
    orden = fecha_dt.sort_values(ascending=False, na_position="last").index
    df = df.loc[orden]
    fecha_dt = fecha_dt.loc[orden]
    n_antes_dedup = len(df)
    mask_keep = ~df.duplicated(subset=DEDUP_KEYS, keep="first")
    df = df[mask_keep]
    fecha_dt = fecha_dt[mask_keep]
    n_eliminadas_dup = n_antes_dedup - len(df)

    # Reemplazar la fecha original por su versión ISO.
    df[FECHA_COL] = fecha_dt.dt.strftime("%Y-%m-%d")

    # Conservar solo las columnas a mantener, en el orden de RENAME, y renombrar.
    df = df[list(RENAME)].rename(columns=RENAME)

    # Orden estable y legible para el archivo de salida (por id numérico).
    df = df.sort_values("id", key=lambda s: pd.to_numeric(s, errors="coerce"))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas totales:                  {total:,}\n"
        f"Filas con fecha inválida:       {n_fecha_invalida:,} "
        f"(Fecha Inscripción no parseable como DD-MM-YYYY; se conservan)\n"
        f"Filas eliminadas por duplicado: {n_eliminadas_dup:,} "
        f"(misma {DEDUP_KEYS[0]} y {DEDUP_KEYS[1]}, se conserva la más reciente)\n"
        f"Filas finales:                  {len(df):,}\n"
        f"Columnas finales:               {list(df.columns)}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
