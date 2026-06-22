"""
Filtra la tabla de zarpes IFOP (`extract_zarpes.py`) a la región de estudio y le
asigna un identificador propio.

Reglas:
  - Solo zarpes cuyo puerto de recalada (arrival) está en la región activa,
    según `REGION_PORT_NAMES` en `processing/utils/ports.py` (derivado del perfil
    de región, `processing/utils/regions.py`). El cruce de nombre → id se hace
    contra `ports.csv` (comparación normalizada: sin tildes, mayúsculas), así que
    no hay ids de puerto cableados acá.
  - Se asigna un `zarpe_id` correlativo (1..N) como primera columna.

No se filtra por especie: muchos zarpes de Atacama no traen especie objetivo en
la ficha de detalle, y filtrar por jurel los dejaría fuera.

Entrada:
  data/processing/ifop/zarpes.csv
  data/processing/ifop/ports.csv   (para resolver nombre de puerto → id)

Salida:
  data/processing/ifop/zarpes_atacama.csv

Uso:
    uv run python -m processing.ifop.filter.filter_zarpes
"""

import sys
import unicodedata
from pathlib import Path

import pandas as pd

from processing.utils.ports import REGION_PORT_NAMES


DATA_DIR    = Path(__file__).resolve().parents[3] / "data"
ZARPES_CSV  = DATA_DIR / "processing" / "ifop" / "zarpes.csv"
PORTS_CSV   = DATA_DIR / "processing" / "ifop" / "ports.csv"
OUTPUT_CSV  = DATA_DIR / "processing" / "ifop" / "zarpes_atacama.csv"


def _normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni espacios sobrantes, para comparar nombres."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_tilde.split()).lower()


def _ids_region(ports: pd.DataFrame) -> set[str]:
    """Resuelve REGION_PORT_NAMES contra ports.csv → conjunto de port_id."""
    objetivo = {_normalizar(n) for n in REGION_PORT_NAMES}
    coincide = ports["port_name"].map(_normalizar).isin(objetivo)
    ids = set(ports.loc[coincide, "port_id"])

    # Avisar si algún nombre esperado no se encontró en el catálogo (cambio de
    # nombre o puerto ausente de los datos): el filtro seguiría, pero más chico.
    encontrados = {_normalizar(n) for n in ports.loc[coincide, "port_name"]}
    faltantes = objetivo - encontrados
    if faltantes:
        print(f"AVISO: {len(faltantes)} puerto(s) de la región no están en "
              f"ports.csv: {sorted(faltantes)}", file=sys.stderr)
    return ids


def filtrar_zarpes(zarpes: pd.DataFrame, ports: pd.DataFrame) -> pd.DataFrame:
    """Recorta a recaladas en la región activa y agrega el zarpe_id correlativo."""
    ids = _ids_region(ports)
    filtrado = zarpes[zarpes["arrival_port_id"].isin(ids)].copy()
    filtrado = filtrado.sort_values(["departure_datetime", "vessel_code"]) \
                       .reset_index(drop=True)
    filtrado.insert(0, "zarpe_id", range(1, len(filtrado) + 1))
    return filtrado


def main() -> None:
    for ruta, etapa in ((ZARPES_CSV, "extract_zarpes"),
                        (PORTS_CSV, "extract_ports")):
        if not ruta.exists():
            print(
                f"ERROR: no existe {ruta}.\n"
                f"       Generalo primero con:\n"
                f"           uv run python -m processing.ifop.identifiers.{etapa}",
                file=sys.stderr,
            )
            sys.exit(1)

    zarpes = pd.read_csv(ZARPES_CSV, dtype=str)
    ports  = pd.read_csv(PORTS_CSV, dtype=str)

    filtrado = filtrar_zarpes(zarpes, ports)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    filtrado.to_csv(OUTPUT_CSV, index=False)

    print(f"Zarpes en Atacama (recalada): {len(filtrado)} de {len(zarpes)}.")
    print(f"\n→ {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
