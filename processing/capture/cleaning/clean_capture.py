"""
Normaliza la bitácora de captura cruda y escribe el resultado a
data/processing/capture[/<source>]/cleaned/capture.csv.

Soporta DOS fuentes de captura (variable de entorno `SOURCE`, ver
processing/utils/datasets.py). Ambas producen el MISMO esquema de salida (formato
ancho: una columna por especie), así que las etapas posteriores son idénticas:

  - `bitacora` (por defecto): `bitacora.csv`, ya en formato ancho (una columna por
    especie), separado por comas.
  - `backup`: `backup.csv`, formato LARGO (una fila por especie por lance),
    separado por `;`, flota artesanal + industrial. Se filtra a la flota
    `Artesanal` y se pivotea a ancho sumando el peso por especie por recalada.

Entrada:
  data/processing/capture/input/<bitacora.csv | backup.csv>   (compartida)

Salida:
  data/processing/capture[/<source>]/cleaned/capture.csv

Transformaciones comunes:
  - COD_BARCO se conserva tal cual (código hexadecimal) y se deriva
    `vessel_code` = `int(COD_BARCO, 16) − 5` (el "Cód. Barco" decimal interno de
    IFOP). Es la inversa de la fórmula de
    processing/ifop/identifiers/extract_vessels.py y la llave para cruzar con los
    zarpes de referencia IFOP. Ver data/bitacora/ifop_cod_barco_README.md.
  - FECHA_HORA_RECALADA → ISO YYYY-MM-DD HH:MM.

Transformaciones específicas de `bitacora`:
  - LATITUD / LONGITUD (formato DDMMSS entero) → grados decimales, luego se
    asigna el puerto más cercano según las coordenadas de puerto de la región
    activa (processing/utils/regions.py → port_coords(); columna PUERTO). Las
    columnas de coordenadas se eliminan del output.
  - Nombres de columnas con punto y coma reemplazados por guion bajo,
    para no corromper el CSV de salida (delimitado con `;`).
  - Columna vacía final eliminada.
  - Filas sin región descartadas.

Transformaciones específicas de `backup`:
  - FLOTA == "Artesanal" (para que el corte coincida con la bitácora).
  - ESPECIE (nombre en español) → columna de especie en inglés; peso por especie
    sumado por recalada (BARCO + FECHA_HORA_RECALADA + puerto) y pivoteado a ancho.
  - PUERTO_DE_RECALADA (nombre) → PORT (Title Case), consumido por el filtro de
    puerto de la región activa aguas abajo (Caldera, Coquimbo, …).

Cubre todos los años disponibles; no filtra por rango global del proyecto (eso
ocurre en filter_capture).
"""

import csv
import math
import sys
from pathlib import Path

import pandas as pd

from processing.utils.datasets import active_source
from processing.utils.regions import active_region
from processing.utils.species import ALL_SPECIES


DATA_DIR = Path(__file__).resolve().parents[3] / "data"

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

# --- Constantes específicas de `backup` (formato largo) --------------------

# ESPECIE (nombre en español del backup) → columna de especie en inglés. Solo se
# mapean las especies conocidas; las demás (nombres sueltos, "LANCE SIN CAPTURA",
# filas mal formadas) se descartan del pivot. Solo JUREL es crítico para el
# análisis; el resto alimenta el flag PRINCIPAL_CATCH aguas abajo.
BACKUP_SPECIES_MAP = {
    "AGUJILLA":         "NEEDLEFISH",
    "ANCHOVETA":        "ANCHOVY",
    "BACALADILLO":      "BLUE_WHITING",
    "BONITO":           "BONITO",
    "CABALLA":          "MACKEREL",
    "CABINZA":          "CABINZA",
    "CORVINA":          "CORVINA",
    "JIBIA":            "SQUID",
    "JUREL":            "JACK_MACKEREL",
    "MACHUELO":         "MACHUELO",
    "MEDUSAS":          "JELLYFISH",
    "PEJERREY DE MAR":  "SILVERSIDE",
    "SARDINA ESPANOLA": "SARDINE",
}

# Nombre de región del backup ("Región de Atacama") → código numérico, para
# paridad de esquema con la bitácora (columna REGION, vestigial aguas abajo: la
# geografía se define por PORT / región activa, no por este código).
BACKUP_REGION_CODES = {
    "arica": 15, "tarapac": 1, "antofagasta": 2, "atacama": 3, "coquimbo": 4,
    "valpara": 5, "higgins": 6, "libertador": 6, "maule": 7, "nuble": 16,
    "biobio": 8, "bio": 8, "araucan": 9, "rios": 14, "lagos": 10, "aysen": 11,
    "magallanes": 12, "metropol": 13,
}


def _backup_region_code(name: str) -> int:
    """Nombre de región del backup → código numérico (0 si no reconocido)."""
    low = str(name).strip().lower()
    for needle, code in BACKUP_REGION_CODES.items():
        if needle in low:
            return code
    return 0


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


def _clean_bitacora(input_csv: Path) -> pd.DataFrame:
    """Limpia la bitácora IFOP (formato ancho, comas) → esquema de salida común."""
    ports = active_region().port_coords()

    df = pd.read_csv(input_csv, sep=",", encoding="latin-1")
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

    print(
        f"Filas en entrada:            {total:,}\n"
        f"Filas sin región descartadas:{n_sin_region:,}\n"
        f"Fechas inválidas descartadas:{n_fechas_invalidas:,}\n"
        f"COD_BARCO no hex (vessel_code nulo): {n_cod_invalido:,}"
    )
    return df


def _clean_backup(input_csv: Path, fleet: str | None) -> pd.DataFrame:
    """Limpia el respaldo nacional (formato largo, `;`) → esquema de salida común.

    Una fila por especie por lance → se pivotea a ancho sumando el peso por especie
    por recalada (BARCO + FECHA_HORA_RECALADA + puerto + región)."""
    # engine="python" + on_bad_lines="skip" tolera las ~0.9% de filas con conteo de
    # campos irregular (comillas/`;` embebidos en observaciones de descarte); esas
    # filas mal formadas casi nunca son capturas de especies conocidas.
    df = pd.read_csv(
        input_csv, sep=";", encoding="latin-1", dtype=str,
        engine="python", quoting=csv.QUOTE_NONE, on_bad_lines="skip",
    )
    total = len(df)

    requeridas = ["BARCO", "FECHA_HORA_RECALADA", "PUERTO_DE_RECALADA",
                  "REGION", "FLOTA", "ESPECIE", "PESO"]
    faltantes = [c for c in requeridas if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en {input_csv.name}: {faltantes}.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Filtro de flota (p.ej. Artesanal), para que el corte coincida con la bitácora.
    if fleet is not None:
        df = df.loc[df["FLOTA"].astype(str).str.strip().str.casefold()
                    == fleet.casefold()].copy()
    n_tras_flota = len(df)

    # ESPECIE (español) → columna en inglés; descartar especies no reconocidas.
    df["_species"] = df["ESPECIE"].astype(str).str.strip().str.upper().map(BACKUP_SPECIES_MAP)
    df = df.dropna(subset=["_species"]).copy()
    df["_peso"] = pd.to_numeric(df["PESO"], errors="coerce").fillna(0.0)

    # Pivot largo → ancho: suma de peso por especie por recalada.
    keys = ["BARCO", "FECHA_HORA_RECALADA", "PUERTO_DE_RECALADA", "REGION"]
    wide = (
        df.pivot_table(index=keys, columns="_species", values="_peso",
                       aggfunc="sum", fill_value=0.0)
        .reset_index()
    )
    wide.columns.name = None

    # Asegurar TODAS las columnas de especies (esquema idéntico a la bitácora).
    for sp in ALL_SPECIES:
        if sp not in wide.columns:
            wide[sp] = 0.0

    # COD_BARCO = BARCO hexadecimal; vessel_code por la inversa de la fórmula.
    wide["COD_BARCO"] = wide["BARCO"].astype(str).str.strip()
    wide["vessel_code"] = wide["COD_BARCO"].map(_vessel_code_desde_cod_barco)
    n_cod_invalido = int(wide["vessel_code"].isna().sum())

    # Fecha: DD-MM-YYYY HH:MM:SS → ISO YYYY-MM-DD HH:MM.
    dt = pd.to_datetime(wide["FECHA_HORA_RECALADA"], format="%d-%m-%Y %H:%M:%S",
                        errors="coerce")
    n_fechas_invalidas = int(dt.isna().sum())
    wide = wide.loc[dt.notna()].copy()
    dt = dt.loc[dt.notna()]
    wide["LANDING_DATETIME"] = dt.dt.strftime("%Y-%m-%d %H:%M")
    wide["YEAR"] = dt.dt.year.astype(int)

    # Puerto de recalada (nombre) → Title Case; región (nombre) → código.
    wide["PORT"] = wide["PUERTO_DE_RECALADA"].astype(str).str.strip().str.title()
    wide["REGION"] = wide["REGION"].map(_backup_region_code)

    front = ["YEAR", "REGION", "COD_BARCO", "vessel_code", "LANDING_DATETIME", "PORT"]
    out = wide[front + ALL_SPECIES]

    print(
        f"Filas en entrada:            {total:,}\n"
        f"Tras filtro de flota ({fleet}): {n_tras_flota:,}\n"
        f"Recaladas (tras pivot):      {len(wide):,}\n"
        f"Fechas inválidas descartadas:{n_fechas_invalidas:,}\n"
        f"COD_BARCO no hex (vessel_code nulo): {n_cod_invalido:,}"
    )
    return out


def main() -> None:
    source = active_source()
    input_csv = DATA_DIR / "processing" / "capture" / "input" / source.input_file
    output_dir = source.scoped(DATA_DIR / "processing" / "capture") / "cleaned"
    output_csv = output_dir / "capture.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no se encontró {input_csv}.\n"
            f"       Copiá ahí el crudo de captura ({source.input_file}).",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Fuente activa (SOURCE): {source.key}  ({source.input_file})")

    if source.key == "backup":
        df = _clean_backup(input_csv, source.fleet)
    else:
        df = _clean_bitacora(input_csv)

    if df.empty:
        print("ERROR: no quedaron filas tras la limpieza.", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, sep=";", index=False, encoding="utf-8")

    print(
        f"Filas escritas:              {len(df):,}\n"
        f"Archivo escrito:             {output_csv}"
    )


if __name__ == "__main__":
    main()
