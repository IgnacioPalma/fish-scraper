"""
Construye la tabla de identificadores de embarcación a partir de los viajes IFOP
limpios (`clean_viajes.py`).

Para cada `vessel_code` (el "Cód. Barco" decimal interno de IFOP, o `id_interno`)
deja una fila con:

  vessel_code  el id_interno IFOP (decimal)
  vessel_name  el nombre de la embarcación
  cod_barco    el código hexadecimal de la bitácora/backup, derivado por la
               fórmula  COD_BARCO = HEX(id_interno + 5)  (mayúsculas)

La fórmula y su derivación están en
`data/bitacora/ifop_cod_barco_README.md`: el `COD_BARCO` de las bitácoras no es
un hash, es `id_interno + 5` escrito en hexadecimal. Esto enlaza la tabla IFOP
con `bitacora_full.csv` / `backup.csv` y con el registro Sernapesca sin cruce
temporal.

Algunos códigos aparecen con más de un nombre (sufijos de matrícula, erratas);
se conserva el nombre más frecuente por código.

Entrada:
  data/processing/ifop/cleaned/ifop_cleaned.csv

Salida:
  data/processing/ifop/vessels.csv   (vessel_code, vessel_name, cod_barco)

Uso:
    uv run python -m processing.ifop.identifiers.extract_vessels
"""

import sys
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
INPUT_CSV  = DATA_DIR / "processing" / "ifop" / "cleaned" / "ifop_cleaned.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "ifop" / "vessels.csv"

# Desplazamiento constante de la fórmula COD_BARCO = HEX(id_interno + OFFSET).
# Ver data/bitacora/ifop_cod_barco_README.md.
COD_BARCO_OFFSET = 5


def cod_barco_desde_id(id_interno: int) -> str:
    """id_interno IFOP → COD_BARCO hexadecimal (mayúsculas)."""
    return format(id_interno + COD_BARCO_OFFSET, "X")


def _nombre_representativo(nombres: pd.Series) -> str | float:
    """Nombre más frecuente de una embarcación (desempate alfabético estable)."""
    presentes = nombres.dropna()
    if presentes.empty:
        return pd.NA
    conteo = presentes.value_counts()
    tope = conteo.max()
    # value_counts ordena por frecuencia; ante empate, el menor alfabético.
    return sorted(conteo[conteo == tope].index)[0]


def extraer_embarcaciones(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por vessel_code, con su nombre representativo y su COD_BARCO."""
    nombres = (df.groupby("vessel_code")["vessel_name"]
                 .apply(_nombre_representativo)
                 .rename("vessel_name")
                 .reset_index())

    nombres["cod_barco"] = nombres["vessel_code"].astype(int).map(cod_barco_desde_id)

    return nombres.sort_values("vessel_code", key=lambda s: s.astype(int)) \
                  .reset_index(drop=True)


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no existe {INPUT_CSV}.\n"
            "       Generá los viajes limpios primero con:\n"
            "           uv run python -m processing.ifop.cleaning.clean_viajes",
            file=sys.stderr,
        )
        sys.exit(1)

    df = pd.read_csv(INPUT_CSV, dtype=str)
    barcos = extraer_embarcaciones(df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    barcos.to_csv(OUTPUT_CSV, index=False)

    sin_nombre = int(barcos["vessel_name"].isna().sum())
    print(f"Embarcaciones únicas: {len(barcos)}")
    if sin_nombre:
        print(f"  sin nombre: {sin_nombre}")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
