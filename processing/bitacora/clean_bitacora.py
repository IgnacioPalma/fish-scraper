"""
Normaliza data/bitacora.csv (bitácora IFOP) y escribe el resultado a
data/bitacora/bitacora_full.csv.

Transformaciones aplicadas:
  - COD_BARCO (RPA en hexadecimal) → columna RPA en decimal.
  - LATITUD / LONGITUD (formato DDMMSS entero) → grados decimales, luego se
    asigna el puerto más cercano según processing/bitacora/puertos_atacama.json
    (columna PUERTO). Las columnas de coordenadas se eliminan del output.
  - FECHA_HORA_RECALADA (formato americano M/D/YYYY HH:MM) → ISO YYYY-MM-DD HH:MM.
  - Nombres de columnas con punto y coma reemplazados por guion bajo,
    para no corromper el CSV de salida (delimitado con `;`).
  - Columna vacía final eliminada.
  - Filas sin región descartadas.

Cubre todos los años disponibles (2012-2024); no filtra por rango global del
proyecto ya que la bitácora se analiza en horizonte histórico propio.
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INPUT_CSV = DATA_DIR / "bitacora.csv"
OUTPUT_DIR = DATA_DIR / "bitacora"
OUTPUT_CSV = OUTPUT_DIR / "bitacora_full.csv"
PORTS_JSON = Path(__file__).resolve().parent / "puertos_atacama.json"

REQUIRED_COLS = ["COD_BARCO", "FECHA_HORA_RECALADA", "LATITUD", "LONGITUD", "REGION"]

COLUMN_RENAME = {
    "AÑO":               "YEAR",
    "REGION":            "REGION",
    "FECHA_HORA_RECALADA": "LANDING_DATETIME",
    "PUERTO":            "PORT",
    "AGUJILLA;PUNTO FIJO": "NEEDLEFISH",
    "ANCHOVETA":         "ANCHOVY",
    "BACALADILLO;MOTE":  "BLUE_WHITING",
    "BONITO;MONO":       "BONITO",
    "CABALLA":           "MACKEREL",
    "CABINZA":           "CABINZA",
    "CORVINA":           "CORVINA",
    "JIBIA":             "SQUID",
    "JUREL":             "JACK_MACKEREL",
    "MACHUELO;TRITRE":   "MACHUELO",
    "MEDUSAS":           "JELLYFISH",
    "PEJERREY DE MAR":   "SILVERSIDE",
    "SARDINA ESPANOLA":  "SARDINE",
}


def _ddmmss_to_decimal(series: pd.Series) -> pd.Series:
    """Convierte una serie de enteros DDMMSS a grados decimales (positivo)."""
    val = series.astype(int)
    grados = val // 10000
    minutos = (val % 10000) // 100
    segundos = val % 100
    return grados + minutos / 60 + segundos / 3600


def _nearest_port(lat: float, lon: float, ports: list) -> str:
    """Retorna el nombre del puerto más cercano usando distancia esférica aproximada."""
    cos_lat = math.cos(math.radians(lat))
    best_name, best_dist = "", float("inf")
    for p in ports:
        dlat = lat - p["latitud"]
        dlon = (lon - p["longitud"]) * cos_lat
        dist = dlat ** 2 + dlon ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = p["nombre"]
    return best_name


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verificá que data/bitacora.csv exista.",
            file=sys.stderr,
        )
        sys.exit(2)

    with PORTS_JSON.open(encoding="utf-8") as f:
        ports = json.load(f)

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

    # Descartar filas sin región y convertir a entero.
    df = df.dropna(subset=["REGION"])
    n_sin_region = total - len(df)
    df["AÑO"] = df["AÑO"].astype(int)
    df["REGION"] = df["REGION"].astype(int)

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

    # Fecha: M/D/YYYY HH:MM → ISO YYYY-MM-DD HH:MM.
    dt = pd.to_datetime(df["FECHA_HORA_RECALADA"], format="%m/%d/%Y %H:%M", errors="coerce")
    n_fechas_invalidas = int(dt.isna().sum())
    df = df.loc[dt.notna()].copy()
    df["FECHA_HORA_RECALADA"] = dt.loc[dt.notna()].dt.strftime("%Y-%m-%d %H:%M")

    # Coordenadas: DDMMSS → grados decimales con signo → puerto más cercano.
    lat_dec = -_ddmmss_to_decimal(df["LATITUD"])
    lon_dec = -_ddmmss_to_decimal(df["LONGITUD"])
    df["PUERTO"] = [
        _nearest_port(lat, lon, ports)
        for lat, lon in zip(lat_dec, lon_dec)
    ]
    df = df.drop(columns=["LATITUD", "LONGITUD"])

    # Reordenar antes de renombrar (usando nombres originales como referencia).
    front = ["AÑO", "REGION", "RPA", "FECHA_HORA_RECALADA", "PUERTO"]
    cols = front + [c for c in df.columns if c not in front]
    df = df[cols]

    # Renombrar todas las columnas al inglés (incluye semicolons → nombres limpios).
    df = df.rename(columns=COLUMN_RENAME)

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
