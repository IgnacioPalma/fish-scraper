"""
Enriquece data/processing/registry/register_clean.csv con dos columnas que convierten al
registro en la ficha central de cada embarcación:

  - IFOP_ID   : "Cód. Barco" decimal interno de IFOP (desde el SIEM Electrónico)
  - COD_BARCO : código hexadecimal usado en las bitácoras / VMS,
                derivado con la fórmula COD_BARCO = HEX(IFOP_ID + 5)
                (ver data/bitacora/ifop_cod_barco_README.md)

El IFOP_ID se obtiene cruzando el NOMBRE de la embarcación contra las
exportaciones HTML del SIEM (data/bitacora/ifop_siem/*.html). Una vez conocido
el IFOP_ID, el COD_BARCO es aritmético: no requiere cruce temporal.

Limitaciones inherentes al cruce por nombre:
  - Solo se enriquecen las embarcaciones cuyo nombre aparece en el SIEM
    (en la práctica, la flota que IFOP ha muestreado). El resto queda en blanco.
  - Homónimos: el registro histórico reutiliza nombres (ej. tres "FORTUNA I").
    El IFOP_ID identifica UN casco; se asigna a la inscripción más reciente con
    ese nombre y los homónimos antiguos quedan en blanco. Estos casos se
    reportan por consola.

El script es idempotente: si las columnas ya existen, las recalcula.

Uso:
    uv run python -m processing.registry.clean_register        # genera el base
    uv run python -m processing.registry.enrich_register_ifop  # añade columnas
"""

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

from processing.bitacora.match_ifop_names import _leer_viajes_ifop

DATA_DIR     = Path(__file__).resolve().parent.parent.parent / "data"
REGISTER_CSV = DATA_DIR / "processing" / "registry" / "register_clean.csv"
BITACORA_CSV = DATA_DIR / "bitacora" / "bitacora_full.csv"
BACKUP_CSV   = DATA_DIR / "backup.csv"

NOMBRE_COL = "Nombre Embarcación"
FECHA_COL  = "Fecha Inscripción"

# Desplazamiento de la fórmula COD_BARCO = HEX(IFOP_ID + OFFSET).
COD_BARCO_OFFSET = 5

# Variantes de nombre conocidas SIEM → registro que el cruce exacto no captura
# (sufijos, separadores, tildes mal codificadas). Clave y valor ya normalizados.
ALIAS_SIEM_A_REGISTRO = {
    "DANIELA ANDREA": "DANIELA ANDREA I",
    "MAI MAU I":      "MAIMAU I",
    "CENTURION II":   "CENTURION II",   # normaliza la � del SIEM (CENTURIÓN)
}


def _normalizar(nombre: str) -> str:
    """Mayúsculas sin tildes, sin guiones, espacios colapsados. El carácter de
    reemplazo '�' (mala codificación de una vocal acentuada) se elimina."""
    s = unicodedata.normalize("NFKD", str(nombre))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper().replace("-", " ").replace("�", "")
    return re.sub(r"\s+", " ", s).strip()


def _cod_barco(ifop_id: int) -> str:
    return format(ifop_id + COD_BARCO_OFFSET, "X")


def _nombre_a_ifop_id() -> dict[str, str]:
    """Tabla nombre_normalizado → IFOP_ID a partir de TODO el SIEM (todos los
    puertos). Si un nombre trae varios IFOP_ID, se toma el más frecuente."""
    viajes = _leer_viajes_ifop()
    viajes["nn"] = viajes["nombre"].map(_normalizar)
    tabla = {}
    for nn, g in viajes.groupby("nn"):
        tabla[nn] = g["id_viaje_ifop"].value_counts().index[0]
    return tabla


def _universo_cod_barco() -> set[str]:
    """COD_BARCO presentes en bitácora + respaldo, para validar la fórmula."""
    universo = set()
    if BITACORA_CSV.exists():
        bf = pd.read_csv(BITACORA_CSV, sep=";", dtype=str)
        universo |= set(bf["COD_BARCO"].str.strip())
    if BACKUP_CSV.exists():
        bk = pd.read_csv(BACKUP_CSV, sep=";", dtype=str)
        universo |= set(bk["BARCO"].str.strip())
    return universo


def main() -> None:
    if not REGISTER_CSV.exists():
        print(
            f"ERROR: no se encontró {REGISTER_CSV}.\n"
            "       Ejecutá primero: uv run python -m processing.registry.clean_register",
            file=sys.stderr,
        )
        sys.exit(2)

    reg = pd.read_csv(REGISTER_CSV, sep=";", dtype=str)
    reg = reg.drop(columns=["IFOP_ID", "COD_BARCO"], errors="ignore")
    reg["_nn"] = reg[NOMBRE_COL].map(_normalizar)
    reg["_fecha"] = pd.to_datetime(reg[FECHA_COL], format="%d-%m-%Y", errors="coerce")

    nombre2id = _nombre_a_ifop_id()
    universo = _universo_cod_barco()

    reg["IFOP_ID"] = ""
    reg["COD_BARCO"] = ""

    homonimos = []
    asignadas = 0
    en_datos = 0
    for nn_siem, ifop_id in nombre2id.items():
        nn_reg = ALIAS_SIEM_A_REGISTRO.get(nn_siem, nn_siem)
        filas = reg.index[reg["_nn"] == nn_reg].tolist()
        if not filas:
            continue
        # Homónimos: el IFOP_ID es de un solo casco → inscripción más reciente.
        if len(filas) > 1:
            idx = reg.loc[filas, "_fecha"].idxmax()
            homonimos.append((nn_reg, len(filas), reg.loc[idx, "Nº RPA"]))
        else:
            idx = filas[0]
        cod = _cod_barco(int(ifop_id))
        reg.at[idx, "IFOP_ID"] = ifop_id
        reg.at[idx, "COD_BARCO"] = cod
        asignadas += 1
        if cod in universo:
            en_datos += 1

    # Coloca IFOP_ID y COD_BARCO junto al nombre de la embarcación.
    cols = [c for c in reg.columns if c not in ("_nn", "_fecha")]
    pos = cols.index(NOMBRE_COL) + 1
    orden = cols[:pos] + ["IFOP_ID", "COD_BARCO"] + \
        [c for c in cols[pos:] if c not in ("IFOP_ID", "COD_BARCO")]
    reg[orden].to_csv(REGISTER_CSV, sep=";", index=False)

    print(f"Embarcaciones del registro: {len(reg)}")
    print(f"Con IFOP_ID + COD_BARCO asignados: {asignadas}")
    print(f"  de los cuales COD_BARCO existe en bitácora/respaldo: {en_datos}")
    if homonimos:
        print(f"\nHomónimos resueltos a la inscripción más reciente ({len(homonimos)}):")
        for nombre, n, rpa in homonimos:
            print(f"  {nombre}: {n} inscripciones → asignado a RPA {rpa}")
    print(f"\n→ {REGISTER_CSV}")


if __name__ == "__main__":
    main()
