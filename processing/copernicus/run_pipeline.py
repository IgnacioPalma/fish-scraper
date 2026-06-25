"""
Orquesta el pipeline Copernicus de punta a punta: descarga las capas marinas que
alimentan el modelo de jurel y las muestrea en cada lance, ejecutando cada etapa
en orden:

  1. download_sst   → data/copernicus/sst_atacama_<rango>.{nc,csv}
  2. download_chl   → data/copernicus/chl_atacama_<rango>.{nc,csv}
  3. download_phy   → data/copernicus/phy_atacama_<rango>.{nc,csv}  (mlotst, so_0m, …)
  4. download_bgc   → data/copernicus/bgc_atacama_<rango>.{nc,csv}  (o2_min_0_200m, nppv)
  5. sample_haul_environment → data/output/zarpes_atacama_haul_env.csv

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el pipeline
se detiene ahí.

La etapa 5 (muestreo) requiere que el pipeline de localizaciones ya haya generado
`data/processing/locations/single_haul/zarpes_atacama_haul_single.csv` (zarpes de
un único lance confiable).

Las descargas necesitan credenciales Copernicus en `.env` (COPERNICUS_USERNAME /
COPERNICUS_PASSWORD) y conexión a internet; son lentas. Con `--skip-download` se
reutilizan las grillas ya descargadas y el pipeline arranca desde el muestreo.

Nota: las capas `sla` y `wind` también viven en `processing.copernicus` pero no
alimentan el producto de lances; se descargan por separado si se necesitan.

Uso:
    uv run python -m processing.copernicus.run_pipeline
    uv run python -m processing.copernicus.run_pipeline --skip-download
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline Copernicus (descarga de capas → muestreo en lances).",
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="No re-descargar las grillas; reutilizar las existentes en data/copernicus/.",
    )
    args = parser.parse_args()

    if args.skip_download:
        print("(--skip-download: se omiten las descargas; se reutilizan las grillas existentes)")
    else:
        _etapa("1/5 · Descarga SST (temperatura superficial)")
        from processing.copernicus import download_sst
        download_sst.main()

        _etapa("2/5 · Descarga CHL (clorofila)")
        from processing.copernicus import download_chl
        download_chl.main()

        _etapa("3/5 · Descarga PHY (MLD + salinidad superficial)")
        from processing.copernicus import download_phy
        download_phy.main()

        _etapa("4/5 · Descarga BGC (O₂ mínimo 0–200 m + nppv)")
        from processing.copernicus import download_bgc
        download_bgc.main()

    _etapa("5/5 · Muestreo de capas en cada lance")
    from processing.copernicus import sample_haul_environment
    sample_haul_environment.main()

    _etapa("Pipeline Copernicus completo")


if __name__ == "__main__":
    main()
