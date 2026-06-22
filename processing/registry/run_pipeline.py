"""
Orquesta el pipeline de registro de punta a punta, ejecutando cada etapa en orden:

  1. scraper       → data/processing/registry/raw/register.csv   (registro NACIONAL, LANCHA)
  2. cleaning      → data/processing/registry/cleaned/register.csv
  3. region_filter → data/processing/registry/region_scoped/register.csv (recorte a la región activa)
  4. filter        → data/processing/registry/filtered/register.csv (categoría LANCHA)
  5. ifop_matching → data/processing/registry/ifop_matched/register.csv
  6. fishing_types → data/processing/registry/fishing_types/register.csv (+ fishing_types.csv)
  7. cerco_filter  → data/processing/registry/register.csv   (producto final)

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

La región del proyecto la define la variable de entorno REGION
(processing/utils/regions.py); la etapa 3 recorta el registro nacional a ella.

Uso:
    uv run python -m processing.registry.run_pipeline
    # Saltarse el scraping de Sernapesca (las dos etapas lentas con red: el
    # listado nacional de la etapa 1 y la consulta por RPA de la etapa 6).
    # Reutiliza raw/register.csv y fishing_types/register.csv existentes:
    uv run python -m processing.registry.run_pipeline --skip-scrape
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline de registro (scraper → cleaning → region_filter → "
        "filter → ifop_matching → fishing_types → cerco_filter)."
    )
    parser.add_argument(
        "--skip-scrape", action="store_true",
        help="No re-scrapear Sernapesca; reutilizar raw/register.csv (etapa 1) y "
        "fishing_types/register.csv (etapa 6) existentes.",
    )
    args = parser.parse_args()

    if args.skip_scrape:
        print("(--skip-scrape: se omiten las etapas 1 y 6; se reutilizan "
              "raw/register.csv y fishing_types/register.csv existentes)")
    else:
        _etapa("1/7 · Scraping del registro nacional (Sernapesca, LANCHA)")
        from processing.registry.scraper import scrape_registry
        scrape_registry.main()

    _etapa("2/7 · Limpieza del registro")
    from processing.registry.cleaning import clean_register
    clean_register.main()

    _etapa("3/7 · Recorte a la región activa")
    from processing.registry.region_filter import filter_region_scope
    filter_region_scope.main()

    _etapa("4/7 · Filtro por categoría (LANCHA)")
    from processing.registry.filter import filter_register
    filter_register.main()

    _etapa("5/7 · Emparejamiento con el catálogo IFOP")
    from processing.registry.ifop_matching import match_ifop_vessels
    match_ifop_vessels.main()

    if not args.skip_scrape:
        _etapa("6/7 · Scraping Sernapesca (señal + arte de JUREL)")
        from processing.registry.fishing_types import scrape_fishing_types
        scrape_fishing_types.main()

    _etapa("7/7 · Filtro final (cerco exclusivo + señal de llamada)")
    from processing.registry.cerco_filter import filter_cerco
    filter_cerco.main()

    _etapa("Pipeline de registro completo")


if __name__ == "__main__":
    main()
