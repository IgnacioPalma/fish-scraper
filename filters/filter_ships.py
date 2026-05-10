"""
Filtra data/ships.csv a los lances de la flota Artesanal en la Región de
Atacama y exporta el resultado a data/ships_filtered.csv.

El CSV de entrada usa ';' como separador y contiene ~93k filas; el filtro
resulta en ~11.5k filas.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INPUT_CSV = DATA_DIR / "ships.csv"
OUTPUT_CSV = DATA_DIR / "ships_filtered.csv"

REGION_VALUE = "Región de Atacama"
FLOTA_VALUE = "Artesanal"


def dms_serie_a_decimal(
    serie: pd.Series, *, hemisferio_negativo: bool = True
) -> pd.Series:
    """Convierte una serie de cadenas DMS empacadas (DDMMSS) a grados decimales.

    SERNAPESCA codifica lat/lon como entero de 6 dígitos sin separadores:
    los primeros 2 son grados, los siguientes 2 minutos, los últimos 2
    segundos. La costa de Atacama es sur + oeste, pero el dato fuente
    no incluye signo; lo aplicamos acá vía `hemisferio_negativo`.

    Cualquier valor que no calce con \\d{6} (vacíos, longitudes raras)
    queda como NaN — no rompemos la fila para no perder la captura.
    """
    s = serie.fillna("").astype(str).str.strip()
    valid = s.str.fullmatch(r"\d{6}")
    deg = pd.to_numeric(s.str[:2], errors="coerce")
    min_ = pd.to_numeric(s.str[2:4], errors="coerce")
    sec = pd.to_numeric(s.str[4:6], errors="coerce")
    decimal = deg + min_ / 60 + sec / 3600
    decimal = decimal.where(valid)
    return -decimal if hemisferio_negativo else decimal


def fecha_zarpe_a_utc_date(serie: pd.Series) -> pd.Series:
    """Convierte FECHA_HORA_ZARPE (hora local Chile) a fecha UTC `YYYY-MM-DD`.

    SERNAPESCA entrega DD-MM-YYYY HH:MM:SS sin zona explícita; la flota
    Artesanal de Atacama opera en Chile continental, así que localizamos
    en America/Santiago (IANA) para que pandas resuelva DST automáticamente
    — el período 2017–2022 cubre cambios de horario de verano irregulares.

    Luego convertimos a UTC y truncamos a fecha, para que la columna
    resultante coincida con el formato del `time` en los CSV de SST/CHL
    (también `YYYY-MM-DD`, también UTC) y permita un merge directo.

    Filas vacías, malformadas o que caen en horas ambiguas/inexistentes
    de DST quedan como NaN (celda vacía en el CSV) en vez de abortar.
    """
    parsed = pd.to_datetime(serie, format="%d-%m-%Y %H:%M:%S", errors="coerce")
    localizado = parsed.dt.tz_localize(
        "America/Santiago", ambiguous="NaT", nonexistent="NaT"
    )
    en_utc = localizado.dt.tz_convert("UTC")
    return en_utc.dt.strftime("%Y-%m-%d").where(en_utc.notna())


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verifica que el archivo de lances esté en data/ships.csv.",
            file=sys.stderr,
        )
        sys.exit(2)

    # El archivo usa ';' como separador (no ',').
    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, low_memory=False)

    faltantes = {"REGION", "FLOTA"} - set(df.columns)
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {sorted(faltantes)}.",
            file=sys.stderr,
        )
        sys.exit(2)

    filtrado = df[(df["REGION"] == REGION_VALUE) & (df["FLOTA"] == FLOTA_VALUE)]

    if filtrado.empty:
        print(
            "ERROR: el filtro no produjo filas. Revisa que los valores\n"
            f"       REGION='{REGION_VALUE}' y FLOTA='{FLOTA_VALUE}' aún existan.",
            file=sys.stderr,
        )
        sys.exit(1)

    faltantes_coords = {"LATITUD", "LONGITUD"} - set(filtrado.columns)
    if faltantes_coords:
        print(
            f"ERROR: faltan columnas de coordenadas: {sorted(faltantes_coords)}.",
            file=sys.stderr,
        )
        sys.exit(2)

    filtrado = filtrado.copy()
    filtrado["LATITUD_DD"] = dms_serie_a_decimal(filtrado["LATITUD"])
    filtrado["LONGITUD_DD"] = dms_serie_a_decimal(filtrado["LONGITUD"])

    n_sin_coord = int(filtrado["LATITUD_DD"].isna().sum())

    if "FECHA_HORA_ZARPE" not in filtrado.columns:
        print(
            "ERROR: falta la columna FECHA_HORA_ZARPE en el CSV.",
            file=sys.stderr,
        )
        sys.exit(2)

    filtrado["FECHA_HORA_ZARPE_UTC"] = fecha_zarpe_a_utc_date(
        filtrado["FECHA_HORA_ZARPE"]
    )
    n_sin_zarpe = int(filtrado["FECHA_HORA_ZARPE_UTC"].isna().sum())

    filtrado.to_csv(OUTPUT_CSV, sep=";", index=False)

    print(
        f"Filas totales:           {len(df):,}\n"
        f"Filas filtradas:         {len(filtrado):,} "
        f"(REGION='{REGION_VALUE}', FLOTA='{FLOTA_VALUE}')\n"
        f"Filas sin coordenada:    {n_sin_coord:,} (LATITUD_DD/LONGITUD_DD = NaN)\n"
        f"Filas sin zarpe UTC:     {n_sin_zarpe:,} (FECHA_HORA_ZARPE_UTC = NaN)\n"
        f"Archivo escrito:         {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
