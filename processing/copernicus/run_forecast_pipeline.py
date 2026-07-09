"""
Orquesta el pipeline de PRONÓSTICO de punta a punta: descarga las capas
marinas de análisis-y-pronóstico (`anfc`) y arma la grilla de predicción que
alimenta al modelo de jurel sobre toda la costa de Atacama, en orden:

  1. download_phy_forecast → data/copernicus/phy_forecast_atacama_<rango>.{nc,csv}  (sst_c, mld_m, sss_psu)
  2. download_bgc_forecast → data/copernicus/bgc_forecast_atacama_<rango>.{nc,csv}  (chl_mg_m3, o2_min_mmol_m3)
  3. build_forecast_grid   → data/output/copernicus/copernicus_forecast_grid_<rango>.csv

A diferencia del pipeline histórico (`run_pipeline`), la ventana temporal es
DINÁMICA hacia adelante: hoy a hoy + ~10 días (horizonte del sistema
operacional global Copernicus). Por eso es un pipeline aparte y NO entra en
`run_all.py` (que vive sobre el rango histórico de entrenamiento).

Las descargas necesitan credenciales Copernicus en `.env` y conexión a
internet. Con `--skip-download` se reutilizan las grillas de pronóstico ya
descargadas y el pipeline arranca desde el armado de la grilla.

Uso:
    uv run python -m processing.copernicus.run_forecast_pipeline
    uv run python -m processing.copernicus.run_forecast_pipeline --skip-download
"""

import argparse


def _etapa(titulo: str) -> None:
    """Imprime un encabezado de etapa."""
    print(f"\n{'=' * 70}\n  {titulo}\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline de pronóstico Copernicus (descarga `anfc` → grilla de predicción).",
    )
    parser.add_argument(
        "--skip-download", action="store_true",
        help="No re-descargar las grillas de pronóstico; reutilizar las existentes.",
    )
    args = parser.parse_args()

    if args.skip_download:
        print("(--skip-download: se omiten las descargas; se reutilizan las grillas de pronóstico existentes)")
    else:
        _etapa("1/3 · Descarga PHY forecast (SST + MLD + salinidad superficial)")
        from processing.copernicus import download_phy_forecast
        download_phy_forecast.main()

        _etapa("2/3 · Descarga BGC forecast (clorofila + O₂ mínimo 0–200 m)")
        from processing.copernicus import download_bgc_forecast
        download_bgc_forecast.main()

    _etapa("3/3 · Armado de la grilla de predicción")
    from processing.copernicus import build_forecast_grid
    build_forecast_grid.main()

    _etapa("Pipeline de pronóstico completo")


if __name__ == "__main__":
    main()
