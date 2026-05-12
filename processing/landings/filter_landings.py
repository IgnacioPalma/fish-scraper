"""
Filtra data/desembarques.csv a los desembarques que cumplen:
  - ano ∈ [START_DATE.year, END_DATE.year]   (rango global del proyecto)
  - region == "Atacama"
  - tipo_agente == "Artesanal"
  - especie == "Jurel"

El resultado se escribe a data/landings/landings_jurel_atacama_artesanal_<rango>.csv
preservando el mismo separador (`;`) y todas las columnas del CSV fuente.

El rango global de fechas viene de processing/utils/date_ranges.py. Para
acotar a un único año, dejá START_DATE y END_DATE dentro de ese año (es lo
que está hoy: 2023). Para incluir varios años, ampliá END_DATE — el filtro
se aplica por año completo, no recorta meses en los bordes del rango.
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE


DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INPUT_CSV = DATA_DIR / "desembarques.csv"
OUTPUT_DIR = DATA_DIR / "landings"

# Valores del filtro (constantes para que un cambio futuro sea un solo lugar).
REGION = "Atacama"
TIPO_AGENTE = "Artesanal"
ESPECIE = "Jurel"

REQUIRED_COLS = ["ano", "region", "tipo_agente", "especie", "toneladas"]


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Verificá que data/desembarques.csv exista en el host.",
            file=sys.stderr,
        )
        sys.exit(2)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # El archivo está en latin-1 (tildes y eñes en region/especie/puerto).
    df = pd.read_csv(INPUT_CSV, sep=";", encoding="latin-1")

    faltantes = [c for c in REQUIRED_COLS if c not in df.columns]
    if faltantes:
        print(
            f"ERROR: faltan columnas requeridas en el CSV: {faltantes}.",
            file=sys.stderr,
        )
        sys.exit(2)

    total = len(df)

    years = list(range(START_DATE.year, END_DATE.year + 1))
    mask = (
        df["ano"].isin(years)
        & (df["region"] == REGION)
        & (df["tipo_agente"] == TIPO_AGENTE)
        & (df["especie"] == ESPECIE)
    )
    filtered = df.loc[mask].copy()

    if filtered.empty:
        print(
            f"ERROR: el filtro no produjo filas para "
            f"ano∈{years[0]}..{years[-1]}, region='{REGION}', "
            f"tipo_agente='{TIPO_AGENTE}', especie='{ESPECIE}'.\n"
            "       Confirmá los valores exactos en la columna correspondiente.",
            file=sys.stderr,
        )
        sys.exit(1)

    year_tag = f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"
    output_csv = OUTPUT_DIR / (
        f"landings_{ESPECIE.lower()}_{REGION.lower()}_"
        f"{TIPO_AGENTE.lower()}_{year_tag}.csv"
    )

    # El CSV fuente tiene tildes; reescribir en UTF-8 para que el downstream
    # (Jupyter, otros scripts) no necesite especificar encoding.
    filtered.to_csv(output_csv, sep=";", index=False, encoding="utf-8")

    toneladas_total = float(filtered["toneladas"].sum())
    print(
        f"Filas totales:           {total:,}\n"
        f"Años filtrados:          {years[0]}..{years[-1]} "
        f"({len(years)} año/s)\n"
        f"Region:                  {REGION}\n"
        f"Tipo agente:             {TIPO_AGENTE}\n"
        f"Especie:                 {ESPECIE}\n"
        f"Filas tras filtro:       {len(filtered):,}\n"
        f"Toneladas totales:       {toneladas_total:,.0f} t\n"
        f"Archivo escrito:         {output_csv}"
    )


if __name__ == "__main__":
    main()
