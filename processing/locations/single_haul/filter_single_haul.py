"""
Recorta los zarpes VMS (`identify_zarpes.py`) a los viajes de UN solo lance.

El nº de lances de cada zarpe no vive en la salida VMS (que es solo estadística
de la traza), sino en el dataset unificado de zarpes con captura
(`data/output/zarpes_atacama_capture.csv`, columna `num_hauls`) —la misma
referencia que usa `identify_zarpes.py` para agrupar. Este paso cruza por
`zarpe_id` —el mismo id de referencia que `identify_zarpes.py` ya asigna— y
conserva únicamente los zarpes con `num_hauls == N_HAULS` (1), tanto en la tabla
de pings como en la tabla resumen.

Entrada:
  data/processing/locations/zarpes/locations_flota_artesanal_<rango>_zarpes.csv
  data/processing/locations/zarpes/zarpes_flota_artesanal_<rango>_summary.csv
  data/output/zarpes_atacama_capture.csv   (columna num_hauls por zarpe_id)

Salidas:
  data/processing/locations/single_haul/locations_flota_artesanal_<rango>_single_haul.csv
  data/processing/locations/single_haul/zarpes_flota_artesanal_<rango>_single_haul_summary.csv

Uso:
    uv run python -m processing.locations.single_haul.filter_single_haul
"""

import sys
from pathlib import Path

import pandas as pd

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import FLEET_NAME


DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "processing" / "locations"
ZARPES_DIR = DATA_DIR / "zarpes"
OUTPUT_DIR = DATA_DIR / "single_haul"
UNIFIED_ZARPES_CSV = DATA_DIR.parent.parent / "output" / "zarpes_atacama_capture.csv"

# Nº de lances que define el filtro (zarpes de un solo lance).
N_HAULS = 1


def _rango_tag() -> str:
    """Etiqueta de rango (`2023` o `2023_2024`), idéntica al resto del pipeline."""
    years = list(range(START_DATE.year, END_DATE.year + 1))
    return f"{years[0]}" if len(years) == 1 else f"{years[0]}_{years[-1]}"


def _ids_un_lance(refs: pd.DataFrame) -> set[int]:
    """zarpe_id de la tabla de referencia cuyo num_hauls == N_HAULS."""
    num = pd.to_numeric(refs["num_hauls"], errors="coerce")
    ids = pd.to_numeric(refs.loc[num == N_HAULS, "zarpe_id"], errors="coerce")
    return set(ids.dropna().astype(int))


def filtrar(pings: pd.DataFrame, resumen: pd.DataFrame,
            refs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Conserva solo los zarpes (pings + resumen) con num_hauls == N_HAULS."""
    ids = _ids_un_lance(refs)
    pings_id = pd.to_numeric(pings["zarpe_id"], errors="coerce")
    resumen_id = pd.to_numeric(resumen["zarpe_id"], errors="coerce")

    pings_out = pings[pings_id.isin(ids)].reset_index(drop=True)
    resumen_out = resumen[resumen_id.isin(ids)].reset_index(drop=True)

    stats = {
        "zarpes_entrada": int(resumen_id.nunique()),
        "zarpes_un_lance": int(resumen_out["zarpe_id"].nunique()),
        "pings_entrada": len(pings),
        "pings_un_lance": len(pings_out),
    }
    return pings_out, resumen_out, stats


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    tag = _rango_tag()
    pings_csv = ZARPES_DIR / f"locations_{FLEET_NAME}_{tag}_zarpes.csv"
    summary_csv = ZARPES_DIR / f"zarpes_{FLEET_NAME}_{tag}_summary.csv"
    out_pings_csv = OUTPUT_DIR / f"locations_{FLEET_NAME}_{tag}_single_haul.csv"
    out_summary_csv = OUTPUT_DIR / f"zarpes_{FLEET_NAME}_{tag}_single_haul_summary.csv"

    for ruta, hint in (
        (pings_csv, "uv run python -m processing.locations.zarpes.identify_zarpes"),
        (summary_csv, "uv run python -m processing.locations.zarpes.identify_zarpes"),
        (UNIFIED_ZARPES_CSV, "uv run python -m processing.capture.unify.unify_zarpes"),
    ):
        if not ruta.exists():
            print(
                f"ERROR: no existe {ruta}.\n"
                f"       Generalo primero con:\n           {hint}",
                file=sys.stderr,
            )
            sys.exit(1)

    pings = pd.read_csv(pings_csv, dtype=str)
    resumen = pd.read_csv(summary_csv, dtype=str)
    refs = pd.read_csv(UNIFIED_ZARPES_CSV, dtype=str)

    pings_out, resumen_out, stats = filtrar(pings, resumen, refs)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pings_out.to_csv(out_pings_csv, index=False)
    resumen_out.to_csv(out_summary_csv, index=False)

    print(
        f"Filtrando zarpes a num_hauls == {N_HAULS} (un solo lance)\n"
        f"  Referencia num_hauls: {UNIFIED_ZARPES_CSV}\n\n"
        f"Zarpes de entrada:        {stats['zarpes_entrada']:,}\n"
        f"  con un solo lance:      {stats['zarpes_un_lance']:,}\n"
        f"Pings de entrada:         {stats['pings_entrada']:,}\n"
        f"  en zarpes de un lance:  {stats['pings_un_lance']:,}\n"
        f"Archivos escritos:\n"
        f"  {out_pings_csv}\n"
        f"  {out_summary_csv}"
    )


if __name__ == "__main__":
    main()
