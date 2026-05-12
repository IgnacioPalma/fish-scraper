"""
Constantes y helpers específicos del formato de los reportes diarios VMS de
Sernapesca (flota artesanal, código de flota 31).

El RANGO de descarga vive en processing/utils/date_ranges.py (rango global del proyecto);
acá vive todo lo demás: URLs, código de flota, constantes de los nombres de
archivo y los dos formatos de URL que coexisten por la migración de CMS
Drupal→WordPress de Sernapesca hacia mediados de 2022.

Dos formatos:

  - Antiguo (Drupal, hasta OLD_FORMAT_END inclusive):
      https://www.sernapesca.cl/sites/default/files/report-YYYY-MM-DD_HH_MM_SS-sernapesca-admin.csv
    En todos los ejemplos observados HH_MM = 11_45 y SS varía entre 00 y 59.
    Se itera SS hasta dar con el archivo.

  - Nuevo (WordPress, a partir de OLD_FORMAT_END + 1 día):
      https://www.sernapesca.cl/app/uploads/YYYY/MM/report_31_YYYYMMDD_flota_artesanal.csv
    Para fechas recientes YYYY/MM coincide con la fecha del reporte. Los
    archivos antiguos de la era WordPress fueron resubidos en bloque a
    /BACKFILL_YEAR_MONTH/, por lo que el script intenta esa ruta como
    respaldo dentro del mismo formato.
"""

from datetime import date
from typing import Iterator


# --- Disponibilidad del archivo Sernapesca --------------------------------
# Primera fecha en la que existe un CSV publicado.
EARLIEST_AVAILABLE = date(2019, 3, 3)

# Última fecha cubierta por el formato Drupal (la siguiente fecha en
# adelante usa WordPress).
OLD_FORMAT_END = date(2022, 6, 30)

# Subida masiva (año, mes) donde WordPress recolocó CSVs antiguos del
# propio formato nuevo. Es un detalle interno del formato nuevo: si la
# subida del mismo mes da 404, se intenta acá.
BACKFILL_YEAR_MONTH = (2023, 11)


# --- Atributos de URL ------------------------------------------------------
FLEET_CODE = "31"
FLEET_NAME = "flota_artesanal"

OLD_BASE = "https://www.sernapesca.cl/sites/default/files"
NEW_BASE = "https://www.sernapesca.cl/app/uploads"

# La hora:minuto del nombre antiguo siempre es 11:45 en los ejemplos
# revisados; los segundos varían (07..26 en la muestra). Iteramos 0..59 para
# cubrir cualquier valor.
OLD_HHMM = "11_45"
OLD_SS_RANGE = range(0, 60)

USER_AGENT = (
    "sst-atacama-bayesian-research/1.0 "
    "(+contacto: ignaciopalma.w@gmail.com)"
)


# --- Constructores de URLs -------------------------------------------------
def build_new_urls(d: date) -> list[str]:
    """URLs candidatas en el formato WordPress, en orden de intento.

    Primero la subida del mismo mes (cubre fechas recientes); luego la
    subida masiva BACKFILL_YEAR_MONTH (cubre archivos antiguos de la era
    WordPress que fueron recolocados ahí).
    """
    yyyymmdd = d.strftime("%Y%m%d")
    filename = f"report_{FLEET_CODE}_{yyyymmdd}_{FLEET_NAME}.csv"

    same_month = f"{NEW_BASE}/{d.year:04d}/{d.month:02d}/{filename}"
    backfill_year, backfill_month = BACKFILL_YEAR_MONTH
    backfill = f"{NEW_BASE}/{backfill_year:04d}/{backfill_month:02d}/{filename}"

    if (d.year, d.month) == BACKFILL_YEAR_MONTH:
        return [same_month]
    return [same_month, backfill]


def build_old_urls(d: date) -> Iterator[str]:
    """URLs candidatas en el formato Drupal, recorriendo SS = 00..59."""
    ymd = d.strftime("%Y-%m-%d")
    for seconds in OLD_SS_RANGE:
        yield (
            f"{OLD_BASE}/report-{ymd}_{OLD_HHMM}_{seconds:02d}"
            f"-sernapesca-admin.csv"
        )
