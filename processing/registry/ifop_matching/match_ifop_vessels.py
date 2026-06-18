"""
Emparejamiento registro ↔ IFOP por nombre (paso 3 del pipeline registry).

Cruza el registro filtrado (data/processing/registry/filtered/register.csv, solo
LANCHAS) contra el catálogo de embarcaciones de IFOP
(data/processing/ifop/vessels.csv, que ya trae `vessel_code` y `cod_barco`) usando
coincidencia difusa de nombres (difflib, mismo enfoque que el resto del proyecto).

Salida: data/processing/registry/ifop_matched/register.csv — SOLO las embarcaciones del
registro que tienen un par en IFOP, con `vessel_code` y `cod_barco` añadidos junto
a las columnas originales del registro.

Notas del cruce por nombre:
  - El nombre se normaliza (mayúsculas, sin tildes ni guiones, espacios
    colapsados) antes de comparar.
  - Solo se conservan coincidencias con score ≥ FUZZY_CUTOFF.
  - Homónimos en IFOP: si un mismo nombre normalizado corresponde a varias
    embarcaciones IFOP (p. ej. dos "GENESIS"), no se puede desambiguar solo por
    nombre; se toma la primera y el caso se reporta por consola.
"""

import difflib
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_CSV = DATA_DIR / "processing" / "registry" / "filtered" / "register.csv"
IFOP_CSV = DATA_DIR / "processing" / "ifop" / "vessels.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "registry" / "ifop_matched" / "register.csv"

NAME_COL = "vessel_name"
# Score mínimo (difflib.SequenceMatcher.ratio) para aceptar una coincidencia.
FUZZY_CUTOFF = 0.85
# Candidatos a evaluar por nombre: si el mejor falla el guardia de sufijo, se
# prueba el siguiente. difflib los entrega de mayor a menor score.
N_CANDIDATOS = 5

_ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
            "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def _normalize(nombre: str) -> str:
    """Mayúsculas sin tildes, sin guiones, espacios colapsados. El carácter de
    reemplazo '�' (mala codificación de una vocal acentuada) se elimina."""
    s = unicodedata.normalize("NFKD", str(nombre))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper().replace("-", " ").replace("�", "")
    return re.sub(r"\s+", " ", s).strip()


def _ordinal(nn: str) -> int | None:
    """Numeral final de un nombre normalizado (romano o dígito) como entero, o
    None si no termina en ordinal. 'ROCIO III'→3, 'LONQUIMAY 2'→2, 'GAROTA'→None."""
    if not nn:
        return None
    ultimo = nn.split()[-1]
    if ultimo in _ROMANOS:
        return _ROMANOS[ultimo]
    if ultimo.isdigit():
        return int(ultimo)
    return None


def _sufijo_compatible(a: str, b: str) -> bool:
    """Guardia de sufijo: rechaza solo cuando AMBOS nombres traen un ordinal y
    estos difieren (ROCIO I vs ROCIO III = cascos distintos). Permite el caso
    sufijo-opcional (DANIELA ANDREA vs DANIELA ANDREA I = mismo casco)."""
    oa, ob = _ordinal(a), _ordinal(b)
    return not (oa is not None and ob is not None and oa != ob)


def main() -> None:
    for ruta, hint in (
        (REGISTRY_CSV, "uv run python -m processing.registry.filter.filter_register"),
        (IFOP_CSV, "uv run python -m processing.ifop.run_pipeline"),
    ):
        if not ruta.exists():
            print(
                f"ERROR: no se encontró {ruta}.\n       Ejecutá primero: {hint}",
                file=sys.stderr,
            )
            sys.exit(2)

    reg = pd.read_csv(REGISTRY_CSV, sep=";", dtype=str)
    ifop = pd.read_csv(IFOP_CSV, sep=",", dtype=str)

    # Catálogo IFOP: nombre normalizado → lista de (vessel_code, cod_barco).
    ifop["_nn"] = ifop[NAME_COL].map(_normalize)
    catalogo: dict[str, list[tuple[str, str]]] = {}
    for nn, g in ifop.groupby("_nn"):
        catalogo[nn] = list(zip(g["vessel_code"], g["cod_barco"]))
    nombres_ifop = list(catalogo)

    reg["_nn"] = reg[NAME_COL].map(_normalize)

    vessel_codes: list[str] = []
    cod_barcos: list[str] = []
    matched_mask: list[bool] = []
    fuzzy_hits: list[tuple[str, str, float]] = []   # (reg_name, ifop_name, score)
    rechazos: list[tuple[str, str, float]] = []     # rechazados por sufijo
    ambiguos: set[str] = set()

    for _, fila in reg.iterrows():
        nn = fila["_nn"]
        # Candidatos de mayor a menor score; se toma el primero que pase el
        # guardia de sufijo (un ordinal distinto en ambos nombres lo descarta).
        candidatos = difflib.get_close_matches(
            nn, nombres_ifop, n=N_CANDIDATOS, cutoff=FUZZY_CUTOFF
        )
        elegido = None
        for nn_ifop in candidatos:
            if _sufijo_compatible(nn, nn_ifop):
                elegido = nn_ifop
                break
            rechazos.append(
                (fila[NAME_COL], nn_ifop,
                 difflib.SequenceMatcher(None, nn, nn_ifop).ratio())
            )
        if elegido is None:
            vessel_codes.append("")
            cod_barcos.append("")
            matched_mask.append(False)
            continue
        score = difflib.SequenceMatcher(None, nn, elegido).ratio()
        entradas = catalogo[elegido]
        if len(entradas) > 1:
            ambiguos.add(elegido)
        code, cod = entradas[0]
        vessel_codes.append(code)
        cod_barcos.append(cod)
        matched_mask.append(True)
        if score < 1.0:
            fuzzy_hits.append((fila[NAME_COL], elegido, score))

    reg["vessel_code"] = vessel_codes
    reg["cod_barco"] = cod_barcos
    matched = reg[pd.Series(matched_mask, index=reg.index)].drop(columns="_nn")
    n_emparejadas = len(matched)

    # Varias filas del registro (homónimos / reinscripciones, p. ej. tres
    # "FORTUNA I") pueden colapsar en un mismo casco IFOP. No se puede asignar con
    # precisión cuál es la embarcación real, así que se descartan TODAS las filas
    # de esos vessel_code (no se conserva ninguna).
    dup_mask = matched["vessel_code"].duplicated(keep=False)
    colapsadas = matched[dup_mask]
    matched = matched[~dup_mask]

    # Colocar vessel_code y cod_barco junto al nombre de la embarcación.
    cols = [c for c in matched.columns if c not in ("vessel_code", "cod_barco")]
    pos = cols.index(NAME_COL) + 1
    orden = cols[:pos] + ["vessel_code", "cod_barco"] + cols[pos:]
    matched = matched[orden]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    matched.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    n_grupos_colapsados = colapsadas["vessel_code"].nunique()
    print(
        f"Registro filtrado (LANCHA):     {len(reg):,}\n"
        f"Catálogo IFOP:                  {len(ifop):,} "
        f"({len(nombres_ifop):,} nombres únicos)\n"
        f"Emparejadas con IFOP:           {n_emparejadas:,}  (corte {FUZZY_CUTOFF})\n"
        f"Descartadas por colapso:        {len(colapsadas):,} "
        f"({n_grupos_colapsados} cascos IFOP con >1 fila del registro)\n"
        f"Filas finales (1 fila/casco):   {len(matched):,}\n"
        f"Sin par en IFOP:                {len(reg) - n_emparejadas:,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )
    if not colapsadas.empty:
        print(
            f"\nDescartadas por colapso (mismo casco IFOP, asignación ambigua) "
            f"({n_grupos_colapsados} cascos):"
        )
        for code, g in colapsadas.groupby("vessel_code"):
            nombres = ", ".join(f"{r.vessel_name} (RPA {r.RPA})" for r in g.itertuples())
            print(f"  vessel_code {code} / cod_barco {g['cod_barco'].iloc[0]}: {nombres}")
    if rechazos:
        vistos = sorted(set(rechazos), key=lambda t: t[2])
        print(
            f"\nRechazadas por guardia de sufijo (ordinal distinto, "
            f"cascos distintos) ({len(vistos)}):"
        )
        for reg_name, ifop_name, score in vistos:
            print(f"  {score:.2f}  registro '{reg_name}'  ✗  IFOP '{ifop_name}'")
    if fuzzy_hits:
        print(f"\nCoincidencias difusas aceptadas (score < 1.0), revisar ({len(fuzzy_hits)}):")
        for reg_name, ifop_name, score in sorted(fuzzy_hits, key=lambda t: t[2]):
            print(f"  {score:.2f}  registro '{reg_name}'  ≈  IFOP '{ifop_name}'")
    if ambiguos:
        print(
            f"\nNombres IFOP con varios cascos (se tomó el primero), "
            f"revisar ({len(ambiguos)}):"
        )
        for nn in sorted(ambiguos):
            opciones = ", ".join(f"{c} ({h})" for c, h in catalogo[nn])
            print(f"  {nn}: {opciones}")


if __name__ == "__main__":
    main()
