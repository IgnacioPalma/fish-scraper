"""
Orquesta el pipeline de registro de punta a punta, ejecutando cada etapa en orden:

  1. cleaning      → data/processing/registry/cleaned/register.csv
  2. filter        → data/processing/registry/filtered/register.csv
  3. ifop_matching → data/processing/registry/ifop_matched/register.csv
  4. fishing_types → data/processing/registry/fishing_types/register.csv (+ fishing_types.csv)
  5. cerco_filter  → data/processing/registry/register.csv   (producto final)

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

Uso:
    uv run python -m processing.registry.run_pipeline
    # Saltarse el scraping de Sernapesca (etapa 4, lenta: una consulta HTTP por
    # RPA). Reutiliza data/processing/registry/fishing_types/register.csv:
    uv run python -m processing.registry.run_pipeline --skip-scrape
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline de registro (cleaning → filter → ifop_matching → "
        "fishing_types → cerco_filter)."
    )
    parser.add_argument(
        "--skip-scrape", action="store_true",
        help="No re-scrapear Sernapesca; reutilizar fishing_types/register.csv existente.",
    )
    args = parser.parse_args()

    _etapa("1/5 · Limpieza del registro")
    from processing.registry.cleaning import clean_register
    clean_register.main()

    _etapa("2/5 · Filtro por categoría (LANCHA)")
    from processing.registry.filter import filter_register
    filter_register.main()

    _etapa("3/5 · Emparejamiento con el catálogo IFOP")
    from processing.registry.ifop_matching import match_ifop_vessels
    match_ifop_vessels.main()

    if args.skip_scrape:
        print("\n(--skip-scrape: se omite la etapa 4; se reutiliza "
              "fishing_types/register.csv existente)")
    else:
        _etapa("4/5 · Scraping Sernapesca (señal + arte de JUREL)")
        from processing.registry.fishing_types import scrape_fishing_types
        scrape_fishing_types.main()

    _etapa("5/5 · Filtro final (cerco exclusivo + señal de llamada)")
    from processing.registry.cerco_filter import filter_cerco
    filter_cerco.main()

    _etapa("Pipeline de registro completo")


if __name__ == "__main__":
    main()
