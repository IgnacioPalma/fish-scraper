"""
Limpia el CSV consolidado de viajes de observadores del SIEM IFOP
(`scrape_siem.py`) y deja una tabla lista para análisis con nombres de columna
en inglés.

Transformaciones (entrada → salida):

  lugar              → embarked          (bool: "Embarcado"→True, "Tierra"→False)
  fecha_zarpe        → departure_datetime (ISO 8601, desde dd/mm/aaaa HH:MM)
  fecha_recalada     → arrival_datetime   (ISO 8601)
  cod_barco          → vessel_code + vessel_name
                       ("940947 - DON BENITO II" → 940947, "DON BENITO II")
  puerto_zarpe       → departure_port_id + departure_port_name
                       ("10 - CALDERA" → 10, "CALDERA")
  puerto_recalada    → arrival_port_id + arrival_port_name

Se descartan las columnas de procedencia del scraping (observador, rut, cargo,
estado_match, score_match): identifican al observador y la calidad del cruce de
nombre, no al viaje.

El "código" siempre es el entero inicial; el resto (que puede contener más
guiones, p.ej. "601599 - PIA - KATA") queda íntegro como nombre.

Entrada:
  data/processing/ifop/raw/viajes_observadores_coquimbo.csv

Salida:
  data/processing/ifop/cleaned/ifop_cleaned.csv

Uso:
    uv run python -m processing.ifop.cleaning.clean_viajes
"""

import sys
import unicodedata
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV  = DATA_DIR / "processing" / "ifop" / "raw" / "viajes_observadores_coquimbo.csv"
OUT_DIR    = DATA_DIR / "processing" / "ifop" / "cleaned"
OUTPUT_CSV = OUT_DIR / "ifop_cleaned.csv"

# Formato de fecha de origen del SIEM (dd/mm/aaaa HH:MM).
FECHA_FMT_ENTRADA = "%d/%m/%Y %H:%M"

# Columnas del scraping que no describen el viaje y se descartan.
COLS_DESCARTE = ["observador", "rut", "cargo", "estado_match", "score_match"]

# "<código entero> - <nombre>"; el nombre captura el resto (puede traer guiones).
RE_COD_NOMBRE = r"^\s*(\d+)\s*-\s*(.*?)\s*$"

# Orden final de columnas en la salida.
COLS_SALIDA = [
    "embarked",
    "departure_datetime", "arrival_datetime",
    "vessel_code", "vessel_name",
    "departure_port_id", "departure_port_name",
    "arrival_port_id", "arrival_port_name",
]


def _normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni espacios sobrantes, para comparar etiquetas."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_tilde.split()).lower()


def _a_booleano(serie: pd.Series) -> pd.Series:
    """"Embarcado"→True, "Tierra"→False; cualquier otro valor → <NA>."""
    norm = serie.map(_normalizar)
    return norm.map({"embarcado": True, "tierra": False}).astype("boolean")


def _estandarizar_fecha(serie: pd.Series) -> pd.Series:
    """Parsea dd/mm/aaaa HH:MM → texto ISO 8601; valores ilegibles → vacío."""
    dt = pd.to_datetime(serie, format=FECHA_FMT_ENTRADA, errors="coerce")
    return dt.dt.strftime("%Y-%m-%d %H:%M:%S")


def _separar_cod_nombre(serie: pd.Series) -> pd.DataFrame:
    """Divide "<código> - <nombre>" en dos columnas (codigo, nombre).

    El código es el entero inicial; el nombre conserva el resto tal cual. Si una
    fila no calza el patrón, ambas columnas quedan vacías. Nombres vacíos
    (p.ej. "600000 -") → <NA>.
    """
    partes = serie.str.extract(RE_COD_NOMBRE)
    partes.columns = ["codigo", "nombre"]
    partes["nombre"] = partes["nombre"].replace("", pd.NA)
    return partes


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica todas las transformaciones y devuelve la tabla final."""
    barco  = _separar_cod_nombre(df["cod_barco"])
    zarpe  = _separar_cod_nombre(df["puerto_zarpe"])
    recala = _separar_cod_nombre(df["puerto_recalada"])

    salida = pd.DataFrame({
        "embarked":            _a_booleano(df["lugar"]),
        "departure_datetime":  _estandarizar_fecha(df["fecha_zarpe"]),
        "arrival_datetime":    _estandarizar_fecha(df["fecha_recalada"]),
        "vessel_code":         barco["codigo"],
        "vessel_name":         barco["nombre"],
        "departure_port_id":   zarpe["codigo"],
        "departure_port_name": zarpe["nombre"],
        "arrival_port_id":     recala["codigo"],
        "arrival_port_name":   recala["nombre"],
    })
    return salida[COLS_SALIDA]


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no existe {INPUT_CSV}.\n"
            "       Generá el CSV de viajes primero con:\n"
            "           uv run python -m processing.ifop.scraper.scrape_siem",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(INPUT_CSV, dtype=str)

    faltantes = [c for c in
                 ["lugar", "fecha_zarpe", "fecha_recalada",
                  "cod_barco", "puerto_zarpe", "puerto_recalada"]
                 if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: al CSV de entrada le faltan columnas esperadas: {faltantes}.\n"
            "       ¿Cambió el formato de salida de scrape_siem.py?",
            file=sys.stderr,
        )
        sys.exit(1)

    limpio = limpiar(df)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limpio.to_csv(OUTPUT_CSV, index=False)

    n_fechas_malas = limpio["departure_datetime"].isna().sum()
    print(f"Filas limpiadas: {len(limpio)} (de {len(df)} de entrada).")
    print(f"  embarked=True:  {int(limpio['embarked'].sum())}")
    print(f"  fecha_zarpe ilegible: {int(n_fechas_malas)}")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
