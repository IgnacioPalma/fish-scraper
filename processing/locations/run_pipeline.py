"""
Orquesta el pipeline de localizaciones (VMS → ubicación del lance) de punta a
punta, ejecutando cada etapa en orden:

  1. scraper           → data/processing/locations/raw_daily/            (un CSV por día)
  2. consolidate       → data/processing/locations/raw_consolidated/
  3. cleaning          → data/processing/locations/cleaned/             (columnas EN, bbox)
  4. filter            → data/processing/locations/filtered/            (flota cerco JUREL + vessel_code)
  5. zarpes            → data/processing/locations/zarpes/              (pings ↔ recalada)
  6. fishing_location  → data/processing/locations/fishing_location/zarpes_atacama_haul_location.csv
  7. single_haul       → data/processing/locations/single_haul/zarpes_atacama_haul_single.csv  ← PRODUCTO LIMPIO

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el
pipeline se detiene ahí.

La etapa 4 (filtro a la flota de cerco) requiere `data/processing/registry/register.csv`
y la etapa 5 requiere `data/processing/capture/zarpes_atacama_capture.csv`; ambos
provienen de pipelines anteriores (ver processing/run_all.py).

Fases (para el orquestador de dos fuentes, ver processing/run_all.py):
  - Etapas 1-4 (descarga → filtro a la flota) son INDEPENDIENTES de la fuente de
    captura (SOURCE): la traza VMS es la misma. `--shared-only` corre solo esas.
  - Etapas 5-7 (asignación de pings → lugar del lance → único lance) SÍ dependen
    de la fuente (leen `capture[/<source>]/zarpes_atacama_capture.csv`).
    `--source-only` corre solo esas, reutilizando el filtrado compartido.
  Sin ninguno de los dos flags corre las 7 (comportamiento por defecto).

Uso:
    uv run python -m processing.locations.run_pipeline
    # Reutiliza los CSV diarios ya descargados y arranca desde la consolidación
    # (la descarga VMS diaria es lenta: recorre ~1000 días):
    uv run python -m processing.locations.run_pipeline --skip-scrape
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline de localizaciones (VMS → ubicación del lance).",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="No re-descargar los reportes VMS diarios; reutilizar los CSV crudos existentes.",
    )
    parser.add_argument(
        "--shared-only", action="store_true",
        help="Solo las etapas independientes de la fuente (1-4: descarga → filtro).",
    )
    parser.add_argument(
        "--source-only", action="store_true",
        help="Solo las etapas dependientes de la fuente (5-7: pings → lugar del lance).",
    )
    args = parser.parse_args()

    run_shared = not args.source_only
    run_source = not args.shared_only

    if run_shared:
        if args.skip_scrape:
            print("(--skip-scrape: se omite la descarga VMS diaria; se reutilizan los CSV crudos)")
        else:
            _etapa("1/7 · Descarga de reportes VMS diarios (Sernapesca)")
            from processing.locations.scraper import download_locations

            download_locations.main()

        _etapa("2/7 · Consolidación de los diarios")
        from processing.locations.consolidate import consolidate_locations

        consolidate_locations.main()

        _etapa("3/7 · Limpieza (columnas EN, bbox de la región)")
        from processing.locations.cleaning import clean_locations

        clean_locations.main()

        _etapa("4/7 · Filtro a la flota de cerco JUREL (+ vessel_code)")
        from processing.locations.filter import filter_registry

        filter_registry.main()

    if run_source:
        _etapa("5/7 · Asignación de pings a zarpes con captura")
        from processing.locations.zarpes import identify_zarpes

        identify_zarpes.main()

        _etapa("6/7 · Identificación del lugar del lance (PRODUCTO: haul_location)")
        from processing.locations.fishing_location import identify_fishing_location

        identify_fishing_location.main()

        _etapa("7/7 · Filtro a zarpes de un único lance confiable (PRODUCTO: haul_single)")
        from processing.locations.single_haul import filter_single_haul

        filter_single_haul.main()

    _etapa("Pipeline de localizaciones completo")


if __name__ == "__main__":
    main()
