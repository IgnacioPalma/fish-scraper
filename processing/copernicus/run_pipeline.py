"""
Orquesta el pipeline Copernicus de punta a punta: descarga las capas marinas que
alimentan el modelo de jurel y las muestrea en cada lance, ejecutando cada etapa
en orden:

  1. download_sst   → data/copernicus/sst_atacama_<rango>.{nc,csv}
  2. download_chl   → data/copernicus/chl_atacama_<rango>.{nc,csv}
  3. download_phy   → data/copernicus/phy_atacama_<rango>.{nc,csv}  (mlotst, so_0m, …)
  4. download_bgc   → data/copernicus/bgc_atacama_<rango>.{nc,csv}  (o2_min_0_200m, nppv)
  5. download_wind  → data/copernicus/wind_atacama_<rango>.{nc,csv} (east/northward_wind)
  6. sample_haul_environment → data/output/zarpes_atacama_haul_env.csv

Cada etapa es el `main()` del módulo correspondiente; si una falla aborta con
código distinto de cero (las etapas ya imprimen una pista en stderr), el pipeline
se detiene ahí.

La etapa 6 (muestreo) requiere que el pipeline de localizaciones ya haya generado
`data/processing/locations/single_haul/zarpes_atacama_haul_single.csv` (zarpes de
un único lance confiable).

Las descargas necesitan credenciales Copernicus en `.env` (COPERNICUS_USERNAME /
COPERNICUS_PASSWORD) y conexión a internet; son lentas. Con `--skip-download` se
reutilizan las grillas ya descargadas y el pipeline arranca desde el muestreo.

Nota: la capa `sla` también vive en `processing.copernicus` pero no alimenta el
producto de lances; se descarga por separado si se necesita.

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
    parser.add_argument(
        "--download-only", action="store_true",
        help="Solo descarga las grillas (independiente de la fuente); omite el muestreo.",
    )
    args = parser.parse_args()

    if args.skip_download:
        print("(--skip-download: se omiten las descargas; se reutilizan las grillas existentes)")
    else:
        _etapa("1/6 · Descarga SST (temperatura superficial)")
        from processing.copernicus import download_sst
        download_sst.main()

        _etapa("2/6 · Descarga CHL (clorofila)")
        from processing.copernicus import download_chl
        download_chl.main()

        _etapa("3/6 · Descarga PHY (MLD + salinidad superficial)")
        from processing.copernicus import download_phy
        download_phy.main()

        _etapa("4/6 · Descarga BGC (O₂ mínimo 0–200 m + nppv)")
        from processing.copernicus import download_bgc
        download_bgc.main()

        _etapa("5/6 · Descarga WIND (viento a 10 m → esfuerzo del viento)")
        from processing.copernicus import download_wind
        download_wind.main()

    if args.download_only:
        _etapa("Descarga Copernicus completa (--download-only: se omite el muestreo)")
        return

    _etapa("6/6 · Muestreo de capas en cada lance")
    from processing.copernicus import sample_haul_environment
    sample_haul_environment.main()

    _etapa("Pipeline Copernicus completo")


if __name__ == "__main__":
    main()
