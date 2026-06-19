"""
Filtra las posiciones VMS limpias (`clean_locations.py`) y deja únicamente los
pings de las embarcaciones del registro de cerco JUREL
(`data/processing/registry/register.csv`).

El reporte VMS de Sernapesca es la flota artesanal **nacional**; este paso lo
recorta a la flota de interés cruzando contra el registro por DOS llaves, y
conserva el ping si coincide por CUALQUIERA de ellas:

  1. Señal: el `signal_code` del registro (numérico, p.ej. `8165`) es la parte
     numérica del `radio_call_sign` del VMS (`CB8165`). Se comparan los dígitos.
  2. Nombre: `vessel_name` normalizado (mayúsculas, sin el sufijo de actividad
     "(ART)"/"(LB)", solo alfanumérico).

En la práctica ambas llaves cubren exactamente los mismos barcos (20 de 28 del
registro aparecen en el VMS de Atacama; el resto no reportó dentro del área),
y coinciden sin conflicto: para cada barco emparejado por nombre, el
`signal_code` es igual a los dígitos de su `radio_call_sign`. Se cruzan ambas
por robustez ante variantes de tipeo o cambios de prefijo en la señal.

A cada ping conservado se le añade `rpa` (el Nº RPA del registro), de modo que
la salida queda trazable a la embarcación registrada.

Entrada:
  data/processing/locations/cleaned/locations_flota_artesanal_<rango>_cleaned.csv
  data/processing/registry/register.csv

Salida:
  data/processing/locations/filtered/locations_flota_artesanal_<rango>_registry.csv

El <rango> se deriva del rango global (processing/utils/date_ranges.py), igual
que en los pasos anteriores del pipeline.

Uso:
    uv run python -m processing.locations.filter.filter_registry
"""

import re
import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing"
CLEANED_DIR = DATA_DIR / "locations" / "cleaned"
OUTPUT_DIR = DATA_DIR / "locations" / "filtered"
REGISTER_CSV = DATA_DIR / "registry" / "register.csv"


def _rango_tag() -> str:
    """Etiqueta de rango (`2023` o `2023_2024`), idéntica al resto del pipeline."""
    years = list(range(START_DATE.year, END_DATE.year + 1))
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"


def _normalizar_nombre(serie: pd.Series) -> pd.Series:
    """Mayúsculas, sin paréntesis ni su contenido, solo alfanumérico.

    "DON PANCRACIO (ART)" → "DONPANCRACIO"; "Kali (LB)" → "KALI".
    """
    s = serie.fillna("").str.upper()
    s = s.str.replace(r"\(.*?\)", "", regex=True)
    s = s.str.replace(r"[^A-Z0-9]", "", regex=True)
    return s


def _solo_digitos(serie: pd.Series) -> pd.Series:
    """Deja solo los dígitos (la señal sin el prefijo de letras): "CB8165" → "8165"."""
    return serie.fillna("").str.replace(r"[^0-9]", "", regex=True)


def filtrar(loc: pd.DataFrame, reg: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Conserva los pings de barcos del registro y les añade `rpa`."""
    # Mapas señal→RPA y nombre_normalizado→RPA desde el registro.
    reg = reg.copy()
    reg["_signal"] = reg["signal_code"].fillna("").astype(str).str.strip()
    reg["_name"] = _normalizar_nombre(reg["vessel_name"])

    signal_to_rpa = dict(zip(reg["_signal"], reg["RPA"]))
    signal_to_rpa.pop("", None)
    name_to_rpa = dict(zip(reg["_name"], reg["RPA"]))
    name_to_rpa.pop("", None)

    rc_digits = _solo_digitos(loc["radio_call_sign"])
    name_norm = _normalizar_nombre(loc["vessel_name"])

    rpa_por_senal = rc_digits.map(signal_to_rpa)
    rpa_por_nombre = name_norm.map(name_to_rpa)

    # Preferir la señal (exacta) y caer al nombre si la señal no coincidió.
    rpa = rpa_por_senal.fillna(rpa_por_nombre)

    out = loc.copy()
    out.insert(0, "rpa", rpa)
    keep = out["rpa"].notna()

    stats = {
        "match_senal": int(rpa_por_senal.notna().sum()),
        "match_nombre": int(rpa_por_nombre.notna().sum()),
        "match_total": int(keep.sum()),
        "barcos_registro": int(reg["RPA"].nunique()),
        "barcos_presentes": int(out.loc[keep, "rpa"].nunique()),
    }
    return out[keep], stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    input_csv = CLEANED_DIR / f"locations_{FLEET_NAME}_{tag}_cleaned.csv"
    output_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{tag}_registry.csv"

    if not input_csv.exists():
        print(
            f"ERROR: no existe {input_csv}.\n"
            "       Generá el CSV limpio primero con:\n"
            "           uv run python -m processing.locations.cleaning.clean_locations",
            file=sys.stderr,
        )
        sys.exit(1)

    if not REGISTER_CSV.exists():
        print(
            f"ERROR: no existe {REGISTER_CSV}.\n"
            "       Generá el registro de cerco primero con:\n"
            "           uv run python -m processing.registry.run_pipeline",
            file=sys.stderr,
        )
        sys.exit(1)

    loc = pd.read_csv(input_csv, dtype=str)
    reg = pd.read_csv(REGISTER_CSV, sep=";", dtype=str)

    filtrado, stats = filtrar(loc, reg)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filtrado.to_csv(output_csv, index=False)

    size_mb = output_csv.stat().st_size / (1024 * 1024)
    print(
        f"Filtrando posiciones VMS a la flota del registro\n"
        f"  Entrada VMS:   {input_csv}\n"
        f"  Registro:      {REGISTER_CSV}\n\n"
        f"Pings de entrada:                {len(loc):,}\n"
        f"  emparejados por señal:         {stats['match_senal']:,}\n"
        f"  emparejados por nombre:        {stats['match_nombre']:,}\n"
        f"Pings conservados (en registro): {stats['match_total']:,}\n"
        f"Barcos del registro presentes:   {stats['barcos_presentes']} / {stats['barcos_registro']}\n"
        f"Archivo escrito:                 {output_csv}\n"
        f"Tamaño:                          {size_mb:.1f} MB"
    )


if __name__ == "__main__":
    main()
