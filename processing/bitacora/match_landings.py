"""
Empareja cada recalada de data/bitacora/bitacora_caldera_jurel.csv con la
embarcación VMS más probable, usando coincidencia espacio-temporal:
para cada recalada, busca qué barco estaba cerca de Caldera y a baja
velocidad dentro de una ventana de tiempo centrada en LANDING_DATETIME.

Entradas:
  data/bitacora/bitacora_caldera_jurel.csv
  data/filter/vms_near_caldera.csv
  data/filter/register_vms_bridge.csv

Salida:
  data/bitacora/bitacora_caldera_jurel_matched.csv
"""

import os
import re
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd


DATA_DIR     = Path(__file__).resolve().parent.parent.parent / "data"
BITACORA_CSV = DATA_DIR / "bitacora" / "bitacora_caldera_jurel.csv"
VMS_CSV      = DATA_DIR / "filter" / "vms_near_caldera.csv"
BRIDGE_CSV   = DATA_DIR / "filter" / "register_vms_bridge.csv"
OUTPUT_CSV   = DATA_DIR / "bitacora" / "bitacora_caldera_jurel_matched.csv"

# Horas de búsqueda antes de la recalada y margen posterior
WINDOW_HOURS = 6
MARGIN_HOURS = 6
# Velocidad máxima para considerar un barco como llegando o atracado
MAX_SPEED_KT = 5.0

VMS_COL_NAME     = "Name"
VMS_COL_RC       = "Radio Call Sign (RC)"
VMS_COL_DATETIME = "LOCATION_DATETIME"
VMS_COL_DIST     = "DIST_KM"
VMS_COL_SPEED    = "SPEED_KT"

_RE_SUFIJO_PAREN = re.compile(r"\s*\([A-Z][A-Z0-9\-]+\)\s*$")
_RE_SUFIJO_LB    = re.compile(r"\s+LB\s*$")


def _normalizar_nombre(nombre: str) -> str:
    """Suprime sufijos de flota y normaliza espacios (igual que bridge_register_vms)."""
    n = _RE_SUFIJO_PAREN.sub("", nombre)
    n = _RE_SUFIJO_LB.sub("", n)
    return re.sub(r"\s+", " ", n).strip().upper()


def _sin_coincidencia() -> dict:
    return {
        "MATCHED_VMS_NAME": "",
        "MATCHED_RC":       "",
        "MATCH_CONFIDENCE": "unmatched",
        "VMS_PING_TIME":    "",
        "VMS_DIST_KM":      "",
        "VMS_SPEED_KT":     "",
    }


def main() -> None:
    for path in (BITACORA_CSV, VMS_CSV, BRIDGE_CSV):
        if not path.exists():
            print(
                f"ERROR: no se encontró {path}.\n"
                "       Ejecutá primero los pasos anteriores del pipeline.",
                file=sys.stderr,
            )
            sys.exit(2)

    df_bita = pd.read_csv(BITACORA_CSV, sep=";", encoding="utf-8")
    df_bita["LANDING_DATETIME"] = pd.to_datetime(
        df_bita["LANDING_DATETIME"], format="%Y-%m-%d %H:%M:%S", errors="coerce"
    )

    df_vms = pd.read_csv(VMS_CSV, sep=";", encoding="utf-8", dtype=str)
    df_vms[VMS_COL_DATETIME] = pd.to_datetime(
        df_vms[VMS_COL_DATETIME], format="%Y-%m-%d %H:%M:%S", errors="coerce"
    )
    df_vms[VMS_COL_DIST]  = pd.to_numeric(df_vms[VMS_COL_DIST],  errors="coerce")
    df_vms[VMS_COL_SPEED] = pd.to_numeric(df_vms[VMS_COL_SPEED], errors="coerce")
    df_vms["_nombre_norm"] = df_vms[VMS_COL_NAME].fillna("").map(_normalizar_nombre)

    # Aplicar filtro de velocidad una sola vez sobre todo el dataset pre-filtrado
    df_vms = df_vms.loc[df_vms[VMS_COL_SPEED].fillna(999) <= MAX_SPEED_KT].copy()
    # Descartar filas sin timestamp válido
    df_vms = df_vms.loc[df_vms[VMS_COL_DATETIME].notna()].copy()

    resultados = []
    for _, fila in df_bita.iterrows():
        ts = fila["LANDING_DATETIME"]
        if pd.isna(ts):
            resultados.append(_sin_coincidencia())
            continue

        t_min = ts - timedelta(hours=WINDOW_HOURS)
        t_max = ts + timedelta(hours=MARGIN_HOURS)

        mask = (df_vms[VMS_COL_DATETIME] >= t_min) & (df_vms[VMS_COL_DATETIME] <= t_max)
        candidatos_df = df_vms.loc[mask]

        if candidatos_df.empty:
            resultados.append(_sin_coincidencia())
            continue

        # Por cada barco único (nombre normalizado), conservar el ping más cercano en tiempo
        mejores = []
        for _, grupo in candidatos_df.groupby("_nombre_norm", sort=False):
            delta = (grupo[VMS_COL_DATETIME] - ts).abs()
            idx_min = delta.idxmin()
            mejores.append(grupo.loc[idx_min])

        if not mejores:
            resultados.append(_sin_coincidencia())
            continue

        confianza = "high" if len(mejores) == 1 else "ambiguous"

        # Ordenar por cercanía temporal al momento de recalada; luego por distancia
        mejores_df = pd.DataFrame(mejores)
        mejores_df["_delta_s"] = (mejores_df[VMS_COL_DATETIME] - ts).abs().dt.total_seconds()
        mejores_df = mejores_df.sort_values(["_delta_s", VMS_COL_DIST], ascending=True)
        ganador = mejores_df.iloc[0]

        ping_time = ganador[VMS_COL_DATETIME]
        resultados.append({
            "MATCHED_VMS_NAME": ganador[VMS_COL_NAME],
            "MATCHED_RC":       ganador[VMS_COL_RC],
            "MATCH_CONFIDENCE": confianza,
            "VMS_PING_TIME":    ping_time.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(ping_time) else "",
            "VMS_DIST_KM":      round(float(ganador[VMS_COL_DIST]), 3) if pd.notna(ganador[VMS_COL_DIST]) else "",
            "VMS_SPEED_KT":     round(float(ganador[VMS_COL_SPEED]), 2) if pd.notna(ganador[VMS_COL_SPEED]) else "",
        })

    df_match = pd.concat(
        [df_bita.reset_index(drop=True), pd.DataFrame(resultados)],
        axis=1,
    )

    tmp = OUTPUT_CSV.with_suffix(".tmp")
    df_match.to_csv(tmp, sep=";", index=False, encoding="utf-8")
    os.replace(tmp, OUTPUT_CSV)

    total       = len(df_match)
    n_high      = (df_match["MATCH_CONFIDENCE"] == "high").sum()
    n_ambiguous = (df_match["MATCH_CONFIDENCE"] == "ambiguous").sum()
    n_unmatched = (df_match["MATCH_CONFIDENCE"] == "unmatched").sum()

    print(
        f"Recaladas en bitácora:              {total:,}\n"
        f"  Alta confianza:                   {n_high:,}  ({100 * n_high / total:.1f}%)\n"
        f"  Ambiguas:                         {n_ambiguous:,}  ({100 * n_ambiguous / total:.1f}%)\n"
        f"  Sin coincidencia:                 {n_unmatched:,}  ({100 * n_unmatched / total:.1f}%)\n"
        f"Archivo escrito:                    {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
