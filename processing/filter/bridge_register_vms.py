"""
Construye una tabla de correspondencia entre los nombres de embarcaciones del
VMS (data/filter/vms_near_caldera.csv) y el registro oficial de embarcaciones
(data/processing/registry/register_clean.csv).

El emparejamiento usa normalización de nombres (supresión de sufijos de flota)
seguida de coincidencia difusa con difflib.

Entrada: data/filter/vms_near_caldera.csv
         data/processing/registry/register_clean.csv
Salida:  data/filter/register_vms_bridge.csv
"""

import difflib
import os
import re
import sys
from pathlib import Path

import pandas as pd


DATA_DIR     = Path(__file__).resolve().parent.parent.parent / "data"
VMS_CSV      = DATA_DIR / "filter" / "vms_near_caldera.csv"
REGISTER_CSV = DATA_DIR / "processing" / "registry" / "register_clean.csv"
OUTPUT_CSV   = DATA_DIR / "filter" / "register_vms_bridge.csv"

FUZZY_CUTOFF = 0.80

VMS_COL_NAME      = "Name"
REGISTER_COL_NAME = "Nombre Embarcación"
REGISTER_COL_RPA  = "Nº RPA"
REGISTER_COL_CAL  = "Caleta"

# Sufijos de flota que Sernapesca agrega al nombre VMS (ej. "(LB)", "(ART)")
_RE_SUFIJO_PAREN = re.compile(r"\s*\([A-Z][A-Z0-9\-]+\)\s*$")
_RE_SUFIJO_LB    = re.compile(r"\s+LB\s*$")


def normalizar_nombre_vms(nombre: str) -> str:
    """Suprime sufijos de flota y normaliza espacios."""
    n = _RE_SUFIJO_PAREN.sub("", nombre)
    n = _RE_SUFIJO_LB.sub("", n)
    return re.sub(r"\s+", " ", n).strip().upper()


def main() -> None:
    for path in (VMS_CSV, REGISTER_CSV):
        if not path.exists():
            print(f"ERROR: no se encontró {path}.", file=sys.stderr)
            sys.exit(2)

    df_vms = pd.read_csv(VMS_CSV, sep=";", usecols=[VMS_COL_NAME], dtype=str, encoding="utf-8")
    df_reg = pd.read_csv(REGISTER_CSV, sep=";", dtype=str)

    for col in (VMS_COL_NAME,):
        if col not in df_vms.columns:
            print(f"ERROR: columna '{col}' no encontrada en {VMS_CSV}.", file=sys.stderr)
            sys.exit(2)

    for col in (REGISTER_COL_NAME, REGISTER_COL_RPA, REGISTER_COL_CAL):
        if col not in df_reg.columns:
            print(f"ERROR: columna '{col}' no encontrada en {REGISTER_CSV}.", file=sys.stderr)
            sys.exit(2)

    # Índice del registro: nombre en mayúsculas → (nombre original, RPA, caleta)
    reg_upper = df_reg[REGISTER_COL_NAME].str.upper().tolist()
    reg_meta  = dict(
        zip(
            reg_upper,
            zip(
                df_reg[REGISTER_COL_NAME],
                df_reg[REGISTER_COL_RPA],
                df_reg[REGISTER_COL_CAL],
            ),
        )
    )

    nombres_vms_raw = df_vms[VMS_COL_NAME].dropna().unique().tolist()
    total_unicos    = len(nombres_vms_raw)

    filas = []
    for raw in sorted(nombres_vms_raw):
        norm = normalizar_nombre_vms(raw)
        candidatos = difflib.get_close_matches(norm, reg_upper, n=1, cutoff=FUZZY_CUTOFF)
        if candidatos:
            match_upper               = candidatos[0]
            reg_nombre, reg_rpa, reg_caleta = reg_meta[match_upper]
            score = difflib.SequenceMatcher(None, norm, match_upper).ratio()
        else:
            reg_nombre = reg_rpa = reg_caleta = ""
            score = 0.0

        filas.append({
            "VMS_NAME_RAW":    raw,
            "VMS_NAME_NORM":   norm,
            "REGISTER_NAME":   reg_nombre,
            "REGISTER_RPA":    reg_rpa,
            "REGISTER_CALETA": reg_caleta,
            "MATCH_SCORE":     round(score, 3),
        })

    df_out      = pd.DataFrame(filas)
    emparejados = (df_out["REGISTER_NAME"].notna() & (df_out["REGISTER_NAME"] != "")).sum()

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_CSV.with_suffix(".tmp")
    df_out.to_csv(tmp, sep=";", index=False, encoding="utf-8")
    os.replace(tmp, OUTPUT_CSV)

    print(
        f"Nombres VMS únicos cerca de Caldera:  {total_unicos:,}\n"
        f"Emparejados al registro:              {emparejados:,}  (corte {FUZZY_CUTOFF})\n"
        f"Sin coincidencia:                     {total_unicos - emparejados:,}\n"
        f"Archivo escrito:                      {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
