"""
Orquesta el pipeline de captura de embarcaciones (vessel capture) de punta a
punta, ejecutando cada etapa en orden:

  1. cleaning  → data/processing/capture/cleaned/capture.csv
  2. filter    → data/processing/capture/capture.csv

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

Entrada:
    data/processing/capture/input/bitacora.csv   (bitácora IFOP cruda)

Uso:
    uv run python -m processing.capture.run_pipeline
"""


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    _etapa("1/2 · Limpieza de la bitácora")
    from processing.capture.cleaning import clean_capture
    clean_capture.main()

    _etapa("2/2 · Filtro a Caldera + jurel (captura positiva)")
    from processing.capture.filter import filter_capture
    filter_capture.main()

    _etapa("Pipeline de captura completo")


if __name__ == "__main__":
    main()
