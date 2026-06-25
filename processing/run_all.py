"""
Orquesta TODO el proyecto de punta a punta: encadena los seis pipelines en el
orden que imponen sus dependencias de datos, hasta dejar el dataset de modelado
`data/output/zarpes_atacama_haul_env.csv`.

Orden (y por qué):

  1. IFOP        → data/processing/ifop/zarpes_atacama.csv + vessels.csv
  2. Registry    → data/processing/registry/register.csv      (usa vessels.csv de IFOP)
  3. Captura     → data/processing/capture/zarpes_atacama_capture.csv     (espina = bitácora; usa vessels de IFOP)
  4. Localizaciones (VMS) → data/processing/locations/fishing_location/zarpes_atacama_haul_location.csv
                                                              (usa register.csv + zarpes_atacama_capture.csv)
  5. Copernicus  → data/output/zarpes_atacama_haul_env.csv    (muestrea capas en cada lance)  ← PRODUCTO FINAL

El pipeline de localizaciones no tiene orquestador propio: sus seis etapas se
ejecutan aquí en orden. El pipeline de emparejamiento VMS↔bitácora NO entra: su
producto (`bitacora_caldera_jurel_matched.csv`) no alimenta el dataset de lances.

Cada etapa es el `main()` del módulo correspondiente; si una falla, el proceso
aborta ahí (las etapas ya imprimen una pista en stderr).

Las etapas de scraping/descarga son lentas y necesitan red (y credenciales en
`.env`). Con los flags se reutilizan los datos ya bajados:
  --skip-scrape           omite TODOS los scrapers (IFOP + Sernapesca + descarga VMS diaria).
  --skip-ifop-scrape      omite SOLO el scraper IFOP (el más lento: abre navegador y
                          recorre el SIEM); deja correr los demás scrapers.
  --skip-registry-scrape  omite SOLO el scraper inicial del registro nacional (etapa 1
                          del pipeline de registro); la consulta por RPA (etapa 6) sí corre.
  --skip-download         omite la descarga de las grillas Copernicus (SST/CHL/PHY/BGC).

Uso:
    uv run python -m processing.run_all
    uv run python -m processing.run_all --skip-ifop-scrape
    # Pipeline completo SIN los dos scrapers iniciales pesados (IFOP SIEM +
    # registro nacional); reutiliza sus crudos y corre todo lo demás:
    uv run python -m processing.run_all --skip-ifop-scrape --skip-registry-scrape
    uv run python -m processing.run_all --skip-scrape
    uv run python -m processing.run_all --skip-scrape --skip-download
"""

import argparse
import sys
from contextlib import contextmanager


def _seccion(titulo: str) -> None:
    """Imprime un encabezado de pipeline (bloque mayor)."""
    print(f"\n{'#' * 70}\n#  {titulo}\n{'#' * 70}")


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa (dentro de un pipeline)."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


@contextmanager
def _argv(*args: str):
    """Ejecuta un main() con un sys.argv controlado y lo restaura al salir.

    Necesario porque cada orquestador/etapa parsea sus propios flags desde
    sys.argv; sin esto, heredarían los flags de run_all y fallarían.
    """
    previo = sys.argv
    sys.argv = ["run_all", *args]
    try:
        yield
    finally:
        sys.argv = previo


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orquesta los seis pipelines del proyecto de punta a punta.",
    )
    parser.add_argument(
        "--skip-scrape", action="store_true",
        help="Omite TODOS los scrapers (IFOP + Sernapesca + descarga VMS diaria); reutiliza los crudos.",
    )
    parser.add_argument(
        "--skip-ifop-scrape", action="store_true",
        help="Omite SOLO el scraper IFOP; deja correr los demás scrapers.",
    )
    parser.add_argument(
        "--skip-registry-scrape", action="store_true",
        help="Omite SOLO el scraper inicial del registro nacional (etapa 1); la "
        "consulta por RPA (etapa 6) sí corre.",
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="Omite la descarga de grillas Copernicus; reutiliza las existentes en data/copernicus/.",
    )
    args = parser.parse_args()

    # --skip-scrape implica saltar cada scraper individual.
    skip_ifop_scrape = args.skip_scrape or args.skip_ifop_scrape
    skip_registry_initial_scrape = args.skip_scrape or args.skip_registry_scrape
    skip_vms_download = args.skip_scrape

    # 1 · IFOP -------------------------------------------------------------
    _seccion("1/5 · Pipeline IFOP (scraper → cleaning → identifiers → filter)")
    from processing.ifop import run_pipeline as ifop_pipeline
    with _argv(*(["--skip-scrape"] if skip_ifop_scrape else [])):
        ifop_pipeline.main()

    # 2 · Registro ---------------------------------------------------------
    _seccion("2/5 · Pipeline de registro (scraper → cleaning → region_filter → filter → ifop_matching → fishing_types → cerco_filter)")
    from processing.registry import run_pipeline as registry_pipeline
    # --skip-scrape omite ambos scrapers del registro; --skip-registry-scrape
    # omite solo el inicial (la consulta por RPA, etapa 6, sí corre).
    if args.skip_scrape:
        registry_argv = ["--skip-scrape"]
    elif skip_registry_initial_scrape:
        registry_argv = ["--skip-initial-scrape"]
    else:
        registry_argv = []
    with _argv(*registry_argv):
        registry_pipeline.main()

    # 3 · Captura ----------------------------------------------------------
    _seccion("3/5 · Pipeline de captura (cleaning → filter → unify)")
    from processing.capture import run_pipeline as capture_pipeline
    with _argv():
        capture_pipeline.main()

    # 4 · Localizaciones (VMS) — sin orquestador propio: etapas en orden ---
    _seccion("4/5 · Pipeline de localizaciones (VMS → ubicación del lance)")
    if skip_vms_download:
        print("(--skip-scrape: se omite la descarga VMS diaria; se reutilizan los CSV crudos)")
    else:
        _etapa("4.1 · Descarga de reportes VMS diarios (Sernapesca)")
        from processing.locations.scraper import download_locations
        with _argv():
            download_locations.main()

    _etapa("4.2 · Consolidación de los diarios")
    from processing.locations.consolidate import consolidate_locations
    with _argv():
        consolidate_locations.main()

    _etapa("4.3 · Limpieza (columnas EN, bbox Atacama)")
    from processing.locations.cleaning import clean_locations
    with _argv():
        clean_locations.main()

    _etapa("4.4 · Filtro a la flota de cerco JUREL (+ vessel_code)")
    from processing.locations.filter import filter_registry
    with _argv():
        filter_registry.main()

    _etapa("4.5 · Asignación de pings a zarpes con captura")
    from processing.locations.zarpes import identify_zarpes
    with _argv():
        identify_zarpes.main()

    _etapa("4.6 · Identificación del lugar del lance (PRODUCTO: haul_location)")
    from processing.locations.fishing_location import identify_fishing_location
    with _argv():
        identify_fishing_location.main()

    _etapa("4.7 · Filtro a zarpes de un único lance confiable (PRODUCTO: haul_single)")
    from processing.locations.single_haul import filter_single_haul
    with _argv():
        filter_single_haul.main()

    # 5 · Copernicus (descarga de capas → muestreo en lances) --------------
    _seccion("5/5 · Pipeline Copernicus (descarga de capas → muestreo en lances)")
    from processing.copernicus import run_pipeline as copernicus_pipeline
    with _argv(*(["--skip-download"] if args.skip_download else [])):
        copernicus_pipeline.main()

    _seccion("Pipeline completo · dataset de modelado en data/output/zarpes_atacama_haul_env.csv")


if __name__ == "__main__":
    main()
