"""
Orquesta TODO el proyecto de punta a punta: encadena los pipelines en el orden
que imponen sus dependencias de datos, hasta dejar UN dataset de modelado POR
FUENTE de captura (`data/output/zarpes_<region>[_<source>]_haul_env.csv`).

Dos fuentes de captura (variable de entorno SOURCE, ver
processing/utils/datasets.py): `bitacora` (por defecto, rutas históricas) y
`backup` (respaldo nacional, anida bajo subdirectorios `backup/`). run_all corre
AMBAS para producir dos datasets comparables. Las etapas caras que NO dependen de
la fuente (IFOP, registro, VMS descarga→filtro, descarga Copernicus) se corren UNA
sola vez; solo la cola dependiente de la fuente (captura → lugar del lance →
muestreo) se repite por fuente.

Orden (y por qué):

  Compartido (una vez):
  1. IFOP        → data/processing/ifop/zarpes_atacama.csv + vessels.csv
  2. Registry    → data/processing/registry/register.csv      (usa vessels.csv de IFOP)
  3. Localizaciones VMS, etapas 1-4 → data/processing/locations/filtered/  (traza compartida)
  4. Copernicus, descarga de capas  → data/copernicus/*.nc                 (grillas compartidas)

  Por fuente (bitacora, backup):
  5. Captura     → data/processing/capture[/<source>]/zarpes_atacama_capture.csv  (espina; usa vessels de IFOP)
  6. Localizaciones VMS, etapas 5-7 → …/single_haul/zarpes_atacama_haul_single.csv
  7. Copernicus, muestreo           → data/output/zarpes_<region>[_<source>]_haul_env.csv  ← PRODUCTO FINAL

Cada pipeline tiene su propio orquestador (`run_pipeline.main()`), incluido el
de localizaciones. El pipeline de emparejamiento VMS↔bitácora NO entra: su
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
import os
import sys
from contextlib import contextmanager

# Fuentes de captura a correr (ver processing/utils/datasets.py). El orden deja
# `bitacora` (rutas históricas) primero y `backup` después.
SOURCES = ["bitacora", "backup"]

# Alcances de especie a correr (ver processing/utils/species_scope.py). `jurel`
# (rutas históricas, solo jurel) primero y `all` (todas las especies) después.
SPECIES_SCOPES = ["jurel", "all"]


def _seccion(titulo: str) -> None:
    """Imprime un encabezado de pipeline (bloque mayor)."""
    print(f"\n{'#' * 70}\n#  {titulo}\n{'#' * 70}")


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

    from processing.capture import run_pipeline as capture_pipeline
    from processing.locations import run_pipeline as locations_pipeline
    from processing.copernicus import run_pipeline as copernicus_pipeline
    from processing.utils.datasets import SOURCES as REGISTERED_SOURCES
    from processing.utils.species_scope import SPECIES_SCOPES as REGISTERED_SCOPES
    from processing.utils.regions import active_region

    # 3 · Localizaciones VMS — etapas COMPARTIDAS (descarga → filtro), una vez ----
    _seccion("3/5 · Localizaciones VMS · etapas compartidas (descarga → filtro a la flota)")
    with _argv(*(["--skip-scrape"] if skip_vms_download else []), "--shared-only"):
        locations_pipeline.main()

    # 4 · Copernicus — descarga de capas COMPARTIDA, una vez ---------------------
    _seccion("4/5 · Copernicus · descarga de capas compartida")
    with _argv(*(["--skip-download"] if args.skip_download else []), "--download-only"):
        copernicus_pipeline.main()

    # 5 · Cola dependiente de la fuente × alcance de especie -----------------------
    # Se corre una vez por cada combinación (SOURCE, SPECIES_SCOPE). El upstream
    # compartido (etapas 1-4, incl. el registro con arte por especie) ya corrió.
    previo_source = os.environ.get("SOURCE")
    previo_scope = os.environ.get("SPECIES_SCOPE")
    try:
        for source in SOURCES:
            if source not in REGISTERED_SOURCES:
                sys.exit(f"ERROR: SOURCE '{source}' no está registrada en datasets.py.")
            os.environ["SOURCE"] = source
            for scope in SPECIES_SCOPES:
                if scope not in REGISTERED_SCOPES:
                    sys.exit(f"ERROR: SPECIES_SCOPE '{scope}' no está registrado en species_scope.py.")
                os.environ["SPECIES_SCOPE"] = scope
                _seccion(
                    f"5/5 · Fuente '{source}' · especies '{scope}' · "
                    "captura → lugar del lance → muestreo"
                )

                with _argv():
                    capture_pipeline.main()
                with _argv("--source-only"):
                    locations_pipeline.main()
                # Reutiliza las grillas ya descargadas: aquí solo se muestrea.
                with _argv("--skip-download"):
                    copernicus_pipeline.main()
    finally:
        for var, previo in (("SOURCE", previo_source), ("SPECIES_SCOPE", previo_scope)):
            if previo is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = previo

    region = active_region().key
    productos = "\n".join(
        f"  data/output/zarpes_{region}"
        f"{'' if s == 'bitacora' else '_' + s}"
        f"{'' if sc == 'jurel' else '_' + REGISTERED_SCOPES[sc].slug}_haul_env.csv"
        for s in SOURCES
        for sc in SPECIES_SCOPES
    )
    _seccion(f"Pipeline completo · datasets de modelado:\n{productos}")


if __name__ == "__main__":
    main()
