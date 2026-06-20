"""
Orquesta el pipeline de captura de embarcaciones (vessel capture) de punta a
punta, ejecutando cada etapa en orden:

  1. cleaning  → data/processing/capture/cleaned/capture.csv
  2. filter    → data/processing/capture/capture.csv
  3. unify     → data/output/zarpes_atacama_capture.csv

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

La etapa 3 (unificación) requiere que el pipeline IFOP ya haya generado
`data/processing/ifop/zarpes_atacama.csv` (y `vessels.csv`); si no existen, la
etapa aborta indicando cómo generarlos.

Entrada:
    data/processing/capture/input/bitacora.csv   (bitácora IFOP cruda)

Uso:
    uv run python -m processing.capture.run_pipeline
"""


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    _etapa("1/3 · Limpieza de la bitácora")
    from processing.capture.cleaning import clean_capture
    clean_capture.main()

    _etapa("2/3 · Filtro a Caldera + jurel (captura positiva)")
    from processing.capture.filter import filter_capture
    filter_capture.main()

    _etapa("3/3 · Unificación con zarpes IFOP")
    from processing.capture.unify import unify_zarpes
    unify_zarpes.main()

    _etapa("Pipeline de captura completo")


if __name__ == "__main__":
    main()
