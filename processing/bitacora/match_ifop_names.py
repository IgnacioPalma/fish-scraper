"""
Construye la tabla de correspondencia
    nombre embarcación ↔ código interno IFOP (id_viaje) ↔ COD_BARCO
para la flota artesanal de jurel que recala en Caldera.

El nombre de la embarcación y su código interno IFOP provienen de las
exportaciones HTML del SIEM Electrónico de IFOP (columna "Cód. Barco" con
formato "<id interno> - <NOMBRE>", más la fecha de recalada y el puerto de
recalada). Esos registros NO contienen el COD_BARCO anonimizado que usan
data/bitacora/bitacora_full.csv y data/backup.csv.

El puente es la marca de tiempo de recalada: para cada recalada IFOP en
Caldera buscamos en la bitácora (y en el respaldo) las recaladas de Caldera
con la MISMA marca temporal (al minuto). El COD_BARCO de esas filas es el
candidato. Como una embarcación recala muchas veces, agregamos por nombre y
nos quedamos con el COD_BARCO por consenso (voto mayoritario): el código
verdadero reaparece en cada recalada de la embarcación, mientras que los
"vecinos" temporales falsos varían y no acumulan votos.

NOTA: los pares (id_interno ↔ COD_BARCO) que produce este cruce revelaron que
la relación es DETERMINISTA: COD_BARCO = HEX(id_interno + 5). Una vez conocida
la fórmula, el cruce temporal de abajo solo sirve como validación. Ver
data/bitacora/ifop_cod_barco_README.md para la derivación y las salvedades.

Entradas:
  data/bitacora/ifop_siem/*.html      (exportaciones SIEM Electrónico IFOP)
  data/bitacora/bitacora_full.csv     (COD_BARCO + LANDING_DATETIME + PORT)
  data/backup.csv                     (BARCO + FECHA_HORA_RECALADA + PUERTO)

Salida:
  data/bitacora/ifop_cod_barco_lookup.csv

Uso:
    uv run python -m processing.bitacora.match_ifop_names
"""

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


DATA_DIR      = Path(__file__).resolve().parent.parent.parent / "data"
IFOP_HTML_DIR = DATA_DIR / "bitacora" / "ifop_siem"
BITACORA_CSV  = DATA_DIR / "bitacora" / "bitacora_full.csv"
BACKUP_CSV    = DATA_DIR / "backup.csv"
OUTPUT_CSV    = DATA_DIR / "bitacora" / "ifop_cod_barco_lookup.csv"

# Código de puerto de Caldera en el SIEM IFOP y nombre en las bitácoras.
CALDERA_PORT_CODE = "10"
CALDERA_PORT_NAME = "CALDERA"

# Tolerancia de emparejamiento temporal, en minutos. La recalada IFOP coincide
# al minuto con la recalada de la bitácora cuando corresponden al mismo viaje;
# ampliarla solo introduce colisiones entre embarcaciones que recalan a horas
# parecidas (verificado: ±0 min → 0 colisiones; ±30 min → 11 colisiones).
TOL_MIN = 0

# Una correspondencia se considera de alta confianza si el COD_BARCO ganador
# supera al segundo más votado por al menos este margen de votos, o si lo
# confirman ambas fuentes (bitácora y respaldo).
MARGEN_VOTOS = 1

# Fila de la columna "Cód. Barco": "<id interno> - <NOMBRE EMBARCACIÓN>".
_RE_COD_BARCO = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")
# Fila de puerto: "<código> - <NOMBRE PUERTO>".
_RE_PUERTO    = re.compile(r"^\s*(\d+)\s*-")
_RE_TAGS      = re.compile(r"<[^>]+>")
_RE_FECHA     = re.compile(r"^\d{2}/\d{2}/\d{4}")


def _limpiar_celda(html: str) -> str:
    """Quita etiquetas, normaliza espacios y resuelve &nbsp;."""
    txt = _RE_TAGS.sub(" ", html).replace("\xa0", " ")
    return re.sub(r"\s+", " ", txt).strip()


def _normalizar_nombre(nombre: str) -> str:
    """Mayúsculas sin tildes, para agrupar variantes (CENTURIÓN/CENTURION)."""
    nfkd = unicodedata.normalize("NFKD", nombre)
    sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tilde).strip().upper()


def _leer_viajes_ifop() -> pd.DataFrame:
    """Parsea todas las exportaciones HTML del SIEM a una tabla de viajes."""
    archivos = sorted(IFOP_HTML_DIR.glob("*.html"))
    if not archivos:
        print(
            f"ERROR: no se encontraron exportaciones HTML en {IFOP_HTML_DIR}.\n"
            "       Copiá ahí los archivos del SIEM Electrónico de IFOP\n"
            "       (cada uno con la tabla de viajes de un observador).",
            file=sys.stderr,
        )
        sys.exit(1)

    registros = []
    for fp in archivos:
        html = fp.read_text(encoding="utf-8", errors="replace")
        for fila in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
            celdas = [_limpiar_celda(c)
                      for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
            # La fila de datos tiene >=7 celdas y la 3.ª es la Fecha Recalada.
            if len(celdas) < 7 or not _RE_FECHA.match(celdas[3]):
                continue
            m_cod = _RE_COD_BARCO.match(celdas[4])
            if not m_cod:
                continue
            m_pr = _RE_PUERTO.match(celdas[6])
            registros.append({
                "id_viaje_ifop":   m_cod.group(1),
                "nombre":          m_cod.group(2),
                "fecha_recalada":  celdas[3],
                "puerto_recalada": m_pr.group(1) if m_pr else "",
            })

    df = pd.DataFrame(registros).drop_duplicates()
    df["dt"] = pd.to_datetime(df["fecha_recalada"],
                              format="%d/%m/%Y %H:%M", errors="coerce")
    df["nombre_norm"] = df["nombre"].map(_normalizar_nombre)
    return df.dropna(subset=["dt"])


def _leer_recaladas_caldera() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (bitácora, respaldo) filtradas a recaladas en Caldera."""
    if not BITACORA_CSV.exists():
        print(f"ERROR: no se encontró {BITACORA_CSV}.", file=sys.stderr)
        sys.exit(1)

    bita = pd.read_csv(BITACORA_CSV, sep=";", dtype=str)
    bita = bita[bita["PORT"].str.strip().str.upper() == CALDERA_PORT_NAME].copy()
    bita["dt"] = pd.to_datetime(bita["LANDING_DATETIME"], errors="coerce")
    bita = bita.dropna(subset=["dt"])
    bita["cod"] = bita["COD_BARCO"].str.strip()

    resp = pd.DataFrame(columns=["cod", "dt"])
    if BACKUP_CSV.exists():
        bk = pd.read_csv(BACKUP_CSV, sep=";", dtype=str)
        bk = bk[bk["PUERTO_DE_RECALADA"].str.strip().str.upper()
                == CALDERA_PORT_NAME].copy()
        bk["dt"] = pd.to_datetime(bk["FECHA_HORA_RECALADA"],
                                  format="%d-%m-%Y %H:%M:%S", errors="coerce")
        bk = bk.dropna(subset=["dt"])
        bk["cod"] = bk["BARCO"].str.strip()
        # El respaldo es por lance: deduplicar a recaladas (barco, instante).
        resp = bk.drop_duplicates(subset=["cod", "dt"])[["cod", "dt"]]

    return bita, resp


def _votar(viajes_barco: pd.DataFrame,
           ref_dt: np.ndarray, ref_cod: np.ndarray) -> Counter:
    """Cuenta, por COD_BARCO, en cuántas recaladas de la embarcación aparece
    como candidato dentro de la tolerancia temporal."""
    votos: Counter = Counter()
    for d in viajes_barco["dt"]:
        d64 = np.datetime64(d, "m")
        diff = np.abs((ref_dt - d64) / np.timedelta64(1, "m"))
        candidatos = set(ref_cod[diff <= TOL_MIN])
        votos.update(candidatos)
    return votos


def main() -> None:
    viajes = _leer_viajes_ifop()
    caldera = viajes[viajes["puerto_recalada"] == CALDERA_PORT_CODE]
    print(f"Viajes IFOP parseados: {len(viajes)} "
          f"(recaladas en Caldera: {len(caldera)}; "
          f"embarcaciones distintas: {caldera['nombre_norm'].nunique()})")

    bita, resp = _leer_recaladas_caldera()
    bita_dt  = bita["dt"].values.astype("datetime64[m]")
    bita_cod = bita["cod"].values
    resp_dt  = resp["dt"].values.astype("datetime64[m]")
    resp_cod = resp["cod"].values

    filas = []
    for nombre_norm, g in caldera.groupby("nombre_norm"):
        nombre = g["nombre"].mode().iloc[0]
        id_viaje = g["id_viaje_ifop"].mode().iloc[0]
        n_recaladas = len(g)

        votos_b = _votar(g, bita_dt, bita_cod)
        votos_r = _votar(g, resp_dt, resp_cod)

        if not votos_b and not votos_r:
            filas.append({
                "ship_name": nombre, "ifop_internal_id": id_viaje,
                "cod_barco": "", "n_recaladas_caldera": n_recaladas,
                "votos_bitacora": 0, "votos_backup": 0,
                "fuente": "sin_match", "confianza": "sin_match",
            })
            continue

        # Fuente primaria: bitácora (universo COD_BARCO del modelado, llega a
        # 2024). Si no votó, recurrimos al respaldo (cobertura 2017-2022).
        votos_pri = votos_b if votos_b else votos_r
        ganador, n_top = votos_pri.most_common(1)[0]
        n_run = votos_pri.most_common(2)[1][1] if len(votos_pri) > 1 else 0

        v_b = votos_b.get(ganador, 0)
        v_r = votos_r.get(ganador, 0)
        confirmado_ambas = v_b > 0 and v_r > 0
        decisivo = (n_top - n_run) >= MARGEN_VOTOS

        if confirmado_ambas or (decisivo and n_top >= 2):
            confianza = "alta"
        elif decisivo:
            confianza = "media"
        else:
            confianza = "baja"

        filas.append({
            "ship_name": nombre,
            "ifop_internal_id": id_viaje,
            "cod_barco": ganador,
            "n_recaladas_caldera": n_recaladas,
            "votos_bitacora": v_b,
            "votos_backup": v_r,
            "fuente": "ambas" if confirmado_ambas
                      else ("bitacora" if votos_b else "backup"),
            "confianza": confianza,
        })

    out = pd.DataFrame(filas).sort_values(
        ["confianza", "n_recaladas_caldera"],
        ascending=[True, False], key=lambda s: s.map(
            {"alta": 0, "media": 1, "baja": 2, "sin_match": 3}).fillna(s)
    )

    # Señala COD_BARCO asignado a más de una embarcación (posible falso match).
    asignados = Counter(out.loc[out["cod_barco"] != "", "cod_barco"])
    out["cod_barco_colision"] = out["cod_barco"].map(
        lambda c: "sí" if c and asignados[c] > 1 else "")

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_CSV, index=False)

    n_match = int((out["cod_barco"] != "").sum())
    print(f"\nEmbarcaciones con COD_BARCO asignado: {n_match} / {len(out)}")
    print(out["confianza"].value_counts().to_string())
    n_coll = int((out["cod_barco_colision"] == "sí").sum())
    if n_coll:
        print(f"⚠ {n_coll} fila(s) con COD_BARCO en colisión (revisar).")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
