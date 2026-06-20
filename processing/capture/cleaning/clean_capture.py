"""
Normaliza la bitácora IFOP cruda y escribe el resultado a
data/processing/capture/cleaned/capture.csv.

Entrada:
  data/processing/capture/input/bitacora.csv   (bitácora IFOP cruda)

Salida:
  data/processing/capture/cleaned/capture.csv

Transformaciones aplicadas:
  - COD_BARCO se conserva tal cual (código hexadecimal de la bitácora IFOP) y se
    deriva `vessel_code` = `int(COD_BARCO, 16) − 5` (el "Cód. Barco" decimal
    interno de IFOP). Es la inversa de la fórmula de
    processing/ifop/identifiers/extract_vessels.py y la llave para cruzar con los
    zarpes de referencia IFOP. Ver data/bitacora/ifop_cod_barco_README.md.
  - LATITUD / LONGITUD (formato DDMMSS entero) → grados decimales, luego se
    asigna el puerto más cercano según
    processing/capture/cleaning/puertos_atacama.json (columna PUERTO). Las
    columnas de coordenadas se eliminan del output.
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


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV = DATA_DIR / "processing" / "capture" / "input" / "bitacora.csv"
OUTPUT_DIR = DATA_DIR / "processing" / "capture" / "cleaned"
OUTPUT_CSV = OUTPUT_DIR / "capture.csv"
PORTS_JSON = Path(__file__).resolve().parent / "puertos_atacama.json"

REQUIRED_COLS = ["COD_BARCO", "FECHA_HORA_RECALADA", "LATITUD", "LONGITUD", "REGION"]

# Desplazamiento constante de la fórmula COD_BARCO = HEX(vessel_code + OFFSET).
# vessel_code = int(COD_BARCO, 16) − OFFSET. Inversa de
# processing/ifop/identifiers/extract_vessels.py:cod_barco_desde_id.
# Ver data/bitacora/ifop_cod_barco_README.md.
COD_BARCO_OFFSET = 5

COLUMN_RENAME = {
    "AÑO":               "YEAR",
    "REGION":            "REGION",
    "COD_BARCO":         "COD_BARCO",
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


def _vessel_code_desde_cod_barco(cod: str):
    """COD_BARCO hexadecimal → vessel_code decimal (id_interno IFOP), como texto.

    Devuelve pd.NA si el código no es un hexadecimal válido.
    """
    try:
        return str(int(cod, 16) - COD_BARCO_OFFSET)
    except (ValueError, TypeError):
        return pd.NA


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
            "       Copiá ahí la bitácora IFOP cruda (bitacora.csv).",
            file=sys.stderr,
        )
        sys.exit(2)

    with PORTS_JSON.open(encoding="utf-8") as f:
        ports = json.load(f)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_CSV, sep=",", encoding="latin-1")
    total = len(df)

    # El header trae la "Ñ" de "AÑO" corrompida como carácter de reemplazo
    # (bytes EF BF BD = U+FFFD), que al leer en latin-1 aparece como "ï¿½".
    # Normalizamos para que las referencias a "AÑO" funcionen.
    df.columns = [c.replace("�", "Ñ").replace("ï¿½", "Ñ") for c in df.columns]

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

    # COD_BARCO: código hexadecimal de la bitácora IFOP. Se deriva vessel_code
    # (el "Cód. Barco" decimal interno de IFOP) por la inversa de la fórmula.
    df["COD_BARCO"] = df["COD_BARCO"].astype(str).str.strip()
    df["vessel_code"] = df["COD_BARCO"].map(_vessel_code_desde_cod_barco)
    n_cod_invalido = int(df["vessel_code"].isna().sum())

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
    front = ["AÑO", "REGION", "COD_BARCO", "vessel_code", "FECHA_HORA_RECALADA", "PUERTO"]
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
        f"COD_BARCO no hex (vessel_code nulo): {n_cod_invalido:,}\n"
        f"Filas escritas:              {len(df):,}\n"
        f"Archivo escrito:             {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
