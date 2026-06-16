"""
Filtra data/bitacora/bitacora_full.csv y escribe
data/bitacora/bitacora_caldera_jurel.csv con las siguientes restricciones:

  - Rango de fechas global del proyecto (utils/date_ranges.py).
  - Puerto de interés: Caldera (utils/ports.py).
  - Especie de interés: JACK_MACKEREL (utils/species.py).

Solo se retienen registros con captura positiva de la especie de interés.
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.ports import PORT_OF_INTEREST
from processing.utils.species import ALL_SPECIES, SPECIES_OF_INTEREST


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INPUT_CSV = DATA_DIR / "bitacora" / "bitacora_full.csv"
OUTPUT_CSV = DATA_DIR / "bitacora" / "bitacora_caldera_jurel.csv"


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Ejecutá primero: uv run python -m processing.bitacora.clean_bitacora",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(INPUT_CSV, sep=";", encoding="utf-8")
    total = len(df)

    if SPECIES_OF_INTEREST not in df.columns:
        print(
            f"ERROR: columna '{SPECIES_OF_INTEREST}' no encontrada en {INPUT_CSV}.\n"
            "       Verificá que clean_bitacora haya procesado el archivo correctamente.",
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

    # Filtro por puerto de interés.
    df = df.loc[df["PORT"] == PORT_OF_INTEREST].copy()
    n_tras_puerto = len(df)

    if n_tras_puerto == 0:
        print(
            f"ERROR: ningún registro corresponde al puerto '{PORT_OF_INTEREST}' "
            f"en el rango de fechas seleccionado.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Filtro por especie de interés: captura positiva.
    df = df.loc[df[SPECIES_OF_INTEREST].notna() & (df[SPECIES_OF_INTEREST] > 0)].copy()
    n_tras_especie = len(df)

    if n_tras_especie == 0:
        print(
            f"ERROR: ningún registro tiene captura positiva de '{SPECIES_OF_INTEREST}' "
            f"en {PORT_OF_INTEREST} dentro del rango de fechas seleccionado.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Captura principal: True si JACK_MACKEREL fue la especie más capturada del viaje.
    cols_especies = [s for s in ALL_SPECIES if s in df.columns]
    row_max = df[cols_especies].max(axis=1)
    df["PRINCIPAL_CATCH"] = df[SPECIES_OF_INTEREST] == row_max

    # Eliminar columnas de otras especies.
    cols_otras = [s for s in ALL_SPECIES if s != SPECIES_OF_INTEREST and s in df.columns]
    df = df.drop(columns=cols_otras)

    df.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Rango de fechas:               {START_DATE} – {END_DATE}\n"
        f"Puerto:                        {PORT_OF_INTEREST}\n"
        f"Especie:                       {SPECIES_OF_INTEREST}\n"
        f"Filas en entrada:              {total:,}\n"
        f"Tras filtro de fechas:         {n_tras_fecha:,}\n"
        f"Tras filtro de puerto:         {n_tras_puerto:,}\n"
        f"Tras filtro de especie:        {n_tras_especie:,}\n"
        f"Archivo escrito:               {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
