"""
Normaliza data/bitacora.csv (bitácora IFOP) y escribe el resultado a
data/bitacora/bitacora_full.csv.

Transformaciones aplicadas:
  - COD_BARCO (RPA en hexadecimal) → columna RPA en decimal.
  - LATITUD / LONGITUD (formato DDMMSS entero) → grados decimales con signo
    negativo (hemisferio sur y oeste).
  - FECHA_HORA_RECALADA (formato americano M/D/YYYY HH:MM) → ISO YYYY-MM-DD HH:MM.
  - Nombres de columnas con punto y coma reemplazados por guion bajo,
    para no corromper el CSV de salida (delimitado con `;`).
  - Columna vacía final eliminada.
  - Filas sin región descartadas.

Cubre todos los años disponibles (2012-2024); no filtra por rango global del
proyecto ya que la bitácora se analiza en horizonte histórico propio.
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INPUT_CSV = DATA_DIR / "bitacora.csv"
OUTPUT_DIR = DATA_DIR / "bitacora"
OUTPUT_CSV = OUTPUT_DIR / "bitacora_full.csv"

REQUIRED_COLS = ["COD_BARCO", "FECHA_HORA_RECALADA", "LATITUD", "LONGITUD", "REGION"]


def _ddmmss_to_decimal(series: pd.Series) -> pd.Series:
    """Convierte una serie de enteros DDMMSS a grados decimales (positivo)."""
    val = series.astype(int)
    grados = val // 10000
    minutos = (val % 10000) // 100
    segundos = val % 100
    return grados + minutos / 60 + segundos / 3600


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verificá que data/bitacora.csv exista.",
            file=sys.stderr,
        )
        sys.exit(2)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_CSV, sep=",", encoding="latin-1")
    total = len(df)

    faltantes = [c for c in REQUIRED_COLS if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {faltantes}.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Eliminar columna vacía final.
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    # Descartar filas sin región.
    df = df.dropna(subset=["REGION"])
    n_sin_region = total - len(df)

    # COD_BARCO (hex) → RPA (decimal).
    df["COD_BARCO"] = df["COD_BARCO"].astype(str).str.strip()
    try:
        df["RPA"] = df["COD_BARCO"].apply(lambda x: int(x, 16))
    except ValueError as exc:
        print(
            f"ERROR: COD_BARCO contiene valores no hexadecimales: {exc}.",
            file=sys.stderr,
        )
        sys.exit(2)
    df = df.drop(columns=["COD_BARCO"])

    # Mover RPA al frente (junto a AÑO y REGION).
    cols = ["AÑO", "REGION", "RPA"] + [
        c for c in df.columns if c not in ("AÑO", "REGION", "RPA")
    ]
    df = df[cols]

    # Fecha: M/D/YYYY HH:MM → ISO YYYY-MM-DD HH:MM.
    dt = pd.to_datetime(df["FECHA_HORA_RECALADA"], format="%m/%d/%Y %H:%M", errors="coerce")
    n_fechas_invalidas = int(dt.isna().sum())
    df = df.loc[dt.notna()].copy()
    df["FECHA_HORA_RECALADA"] = dt.loc[dt.notna()].dt.strftime("%Y-%m-%d %H:%M")

    # Coordenadas: DDMMSS → grados decimales con signo.
    df["LATITUD"] = -_ddmmss_to_decimal(df["LATITUD"])
    df["LONGITUD"] = -_ddmmss_to_decimal(df["LONGITUD"])

    # Renombrar columnas con punto y coma para no corromper el CSV de salida.
    df = df.rename(columns=lambda c: c.replace(";", "_"))

    if df.empty:
        print(
            "ERROR: no quedaron filas tras la limpieza.",
            file=sys.stderr,
        )
        sys.exit(1)

    df.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas en entrada:            {total:,}\n"
        f"Filas sin región descartadas:{n_sin_region:,}\n"
        f"Fechas inválidas descartadas:{n_fechas_invalidas:,}\n"
        f"Filas escritas:              {len(df):,}\n"
        f"Archivo escrito:             {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
