"""
Filtra data/processing/capture/cleaned/capture.csv y escribe
data/processing/capture/capture.csv con las siguientes restricciones:

  - Rango de fechas global del proyecto (utils/date_ranges.py).
  - Puerto(s) de interés de la región activa (utils/regions.py → ports_of_interest;
    por defecto Caldera).
  - Especie de interés: JACK_MACKEREL (utils/species.py).

Solo se retienen registros con captura positiva de la especie de interés.
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.datasets import active_source
from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.regions import active_region
from processing.utils.species import ALL_SPECIES, SPECIES_OF_INTEREST
from processing.utils.species_scope import active_species_scope


DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def main() -> None:
    # Rutas scopeadas por fuente (SOURCE) y alcance de especies (SPECIES_SCOPE):
    # `bitacora`+`jurel` conservan las rutas históricas; `backup` anida bajo
    # capture/backup/ y `all` bajo …/all_species/.
    # La ENTRADA (cleaned/capture.csv) es común a todos los alcances de especie
    # (clean_capture es especie-agnóstico), así que NO se scopea por especie.
    scope = active_species_scope()
    source_capture_dir = active_source().scoped(DATA_DIR / "processing" / "capture")
    capture_dir = scope.scoped(source_capture_dir)
    INPUT_CSV = source_capture_dir / "cleaned" / "capture.csv"
    OUTPUT_DIR = capture_dir
    OUTPUT_CSV = OUTPUT_DIR / "capture.csv"

    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Ejecutá primero: uv run python -m processing.capture.cleaning.clean_capture",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(INPUT_CSV, sep=";", encoding="utf-8")
    total = len(df)

    if SPECIES_OF_INTEREST not in df.columns:
        print(
            f"ERROR: columna '{SPECIES_OF_INTEREST}' no encontrada en {INPUT_CSV}.\n"
            "       Verificá que clean_capture haya procesado el archivo correctamente.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Filtro por rango de fechas global.
    df["LANDING_DATETIME"] = pd.to_datetime(
        df["LANDING_DATETIME"], format="%Y-%m-%d %H:%M", errors="coerce"
    )
    mask_fechas = (df["LANDING_DATETIME"].dt.date >= START_DATE) & (
        df["LANDING_DATETIME"].dt.date <= END_DATE
    )
    df = df.loc[mask_fechas].copy()
    n_tras_fecha = len(df)

    if n_tras_fecha == 0:
        print(
            f"ERROR: ningún registro cae dentro del rango de fechas "
            f"{START_DATE} – {END_DATE}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filtro por puerto(s) de interés de la región activa.
    ports_of_interest = active_region().ports_of_interest
    df = df.loc[df["PORT"].isin(ports_of_interest)].copy()
    n_tras_puerto = len(df)

    if n_tras_puerto == 0:
        print(
            f"ERROR: ningún registro corresponde a puerto(s) {list(ports_of_interest)} "
            f"en el rango de fechas seleccionado.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filtro por captura positiva. Según el alcance de especies (SPECIES_SCOPE):
    #   - `jurel`: solo recaladas con jurel > 0 (comportamiento histórico).
    #   - `all`:   recaladas con captura positiva de CUALQUIER especie.
    cols_especies = [s for s in ALL_SPECIES if s in df.columns]
    if scope.require_jurel:
        mask_especie = df[SPECIES_OF_INTEREST].notna() & (df[SPECIES_OF_INTEREST] > 0)
        etiqueta_especie = SPECIES_OF_INTEREST
    else:
        mask_especie = df[cols_especies].fillna(0).gt(0).any(axis=1)
        etiqueta_especie = "cualquier especie"
    df = df.loc[mask_especie].copy()
    n_tras_especie = len(df)

    if n_tras_especie == 0:
        print(
            f"ERROR: ningún registro tiene captura positiva de '{etiqueta_especie}' "
            f"en {list(ports_of_interest)} dentro del rango de fechas seleccionado.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Captura principal: True si JACK_MACKEREL fue la especie más capturada del viaje.
    cols_especies = [s for s in ALL_SPECIES if s in df.columns]
    row_max = df[cols_especies].max(axis=1)
    df["PRINCIPAL_CATCH"] = df[SPECIES_OF_INTEREST] == row_max

    # Eliminar columnas de otras especies (solo en `jurel`; `all` las conserva).
    if not scope.keep_all_species:
        cols_otras = [s for s in ALL_SPECIES if s != SPECIES_OF_INTEREST and s in df.columns]
        df = df.drop(columns=cols_otras)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Rango de fechas:               {START_DATE} – {END_DATE}\n"
        f"Puerto(s):                     {', '.join(ports_of_interest)}\n"
        f"Especie(s):                    {etiqueta_especie}\n"
        f"Filas en entrada:              {total:,}\n"
        f"Tras filtro de fechas:         {n_tras_fecha:,}\n"
        f"Tras filtro de puerto:         {n_tras_puerto:,}\n"
        f"Tras filtro de especie:        {n_tras_especie:,}\n"
        f"Archivo escrito:               {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
