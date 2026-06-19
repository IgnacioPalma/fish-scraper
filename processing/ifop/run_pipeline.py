"""
Orquesta el pipeline IFOP de punta a punta, ejecutando cada etapa en orden:

  1. scraper       → data/processing/ifop/raw/viajes_observadores.csv
  2. cleaning      → data/processing/ifop/cleaned/ifop_cleaned.csv
  3. identifiers   → data/processing/ifop/ports.csv  +  data/processing/ifop/vessels.csv

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

Uso:
    uv run python -m processing.ifop.run_pipeline
    # Reutiliza el CSV crudo existente y arranca desde la limpieza (la etapa de
    # scraping es lenta: abre un navegador y recorre el SIEM):
    uv run python -m processing.ifop.run_pipeline --skip-scrape
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline IFOP (scraper → cleaning → identifiers).")
    parser.add_argument(
        "--skip-scrape", action="store_true",
        help="No re-scrapear el SIEM; reutilizar el CSV crudo existente.",
    )
    args = parser.parse_args()

    if args.skip_scrape:
        print("(--skip-scrape: se omite el scraping; se reutiliza el CSV crudo existente)")
    else:
        _etapa("1/3 · Scraping del SIEM IFOP")
        from processing.ifop.scraper import scrape_siem
        scrape_siem.main()

    _etapa("2/3 · Limpieza de viajes")
    from processing.ifop.cleaning import clean_viajes
    clean_viajes.main()

    _etapa("3/3 · Tablas de identificadores (puertos + embarcaciones)")
    from processing.ifop.identifiers import extract_ports, extract_vessels
    extract_ports.main()
    extract_vessels.main()

    _etapa("Pipeline IFOP completo")


if __name__ == "__main__":
    main()
