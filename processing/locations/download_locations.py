"""
Descarga los reportes diarios VMS de Sernapesca (flota artesanal, código 31)
y los guarda como un CSV por día en data/locations/ (relativo a la raíz del proyecto).

- El rango GLOBAL de fechas viene de processing/utils/date_ranges.py (variables
  START_DATE y END_DATE). Se aplica a todo el proyecto.
- Las constantes específicas del formato Sernapesca (URLs, código de flota,
  límite Drupal↔WordPress, backfill) viven  en processing/utils/locations_common.py.

El script intersecta el rango global con cada era de formato. Cada fecha
queda en EXACTAMENTE un formato (sin fallback cruzado entre Drupal y
WordPress); si el rango global cae fuera del archivo Sernapesca, el script
imprime el motivo y sale sin descargar nada.

El script es idempotente: si el archivo destino ya existe se salta esa fecha,
por lo que se puede interrumpir y volver a correr sin re-descargar.

No requiere credenciales: el sitio de Sernapesca es público.
"""

import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from processing.utils.date_ranges import END_DATE, START_DATE
from processing.utils.locations_common import (
    EARLIEST_AVAILABLE,
    FLEET_NAME,
    OLD_FORMAT_END,
    OLD_SS_RANGE,
    USER_AGENT,
    build_new_urls,
    build_old_urls,
)


OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "locations"

REQUEST_TIMEOUT = 30        # segundos por solicitud HTTP
REQUEST_DELAY = 0.5         # segundos entre solicitudes que tocan la red
MAX_RETRIES = 2             # reintentos para errores 5xx / red transitoria


def iter_dates(start: date, end: date) -> Iterator[date]:
    """Itera día por día entre start y end (ambos inclusive)."""
    current = start
    one_day = timedelta(days=1)
    while current <= end:
        yield current
        current += one_day


def http_get(url: str) -> bytes | None:
    """Descarga el contenido de la URL.

    Devuelve los bytes en caso de 200, o None si el recurso no existe (404).
    Reintenta hasta MAX_RETRIES ante errores 5xx o problemas transitorios de
    red; si persisten, propaga la excepción para que el llamador decida.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if 500 <= exc.code < 600 and attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                last_exc = exc
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                last_exc = exc
                continue
            raise

    # Inalcanzable: el bucle siempre retorna, levanta o continúa.
    raise RuntimeError(f"Reintentos agotados sin éxito ni excepción: {last_exc}")


def save_atomically(content: bytes, dest: Path) -> None:
    """Escribe primero a un archivo temporal y luego renombra al destino,
    para no dejar archivos a medio escribir si el proceso se interrumpe."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(content)
    os.replace(tmp, dest)


def fetch_old(d: date, dest: Path) -> tuple[str, str, int]:
    """Descarga el CSV de d usando el formato Drupal (sweep SS = 00..59)."""
    attempts = 0
    for ss, url in zip(OLD_SS_RANGE, build_old_urls(d)):
        attempts += 1
        content = http_get(url)
        time.sleep(REQUEST_DELAY)
        if content is not None:
            save_atomically(content, dest)
            return "old", f"SS={ss:02d}", attempts
    return "missing", "", attempts


def fetch_new(d: date, dest: Path) -> tuple[str, str, int]:
    """Descarga el CSV de d usando el formato WordPress (same-month luego backfill)."""
    attempts = 0
    new_urls = build_new_urls(d)
    labels = ["same-month", "backfill"][: len(new_urls)]
    for url, label in zip(new_urls, labels):
        attempts += 1
        content = http_get(url)
        time.sleep(REQUEST_DELAY)
        if content is not None:
            save_atomically(content, dest)
            return "new", label, attempts
    return "missing", "", attempts


def main() -> None:
    # En Docker stdout suele estar bufferizado por bloque; con line-buffering
    # cada print() aparece al instante en `docker compose run` (PYTHONUNBUFFERED
    # en docker-compose.yml es el segundo cinturón).
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today()

    # Intersección del rango global con cada era de formato.
    old_start = max(START_DATE, EARLIEST_AVAILABLE)
    old_end = min(END_DATE, OLD_FORMAT_END)

    new_start = max(START_DATE, OLD_FORMAT_END + timedelta(days=1))
    new_end = min(END_DATE, today)

    ranges: list[tuple[str, date, date, callable]] = []
    if old_start <= old_end:
        ranges.append(("antiguo", old_start, old_end, fetch_old))
    if new_start <= new_end:
        ranges.append(("nuevo", new_start, new_end, fetch_new))

    if not ranges:
        print(
            f"Rango global {START_DATE}–{END_DATE} no intersecta con datos "
            f"Sernapesca ({EARLIEST_AVAILABLE} en adelante). Nada que descargar.",
            file=sys.stderr,
        )
        sys.exit(0)

    total_dates = sum((end - start).days + 1 for _, start, end, _ in ranges)
    width = len(str(total_dates))

    print(
        f"Descargando reportes diarios VMS de Sernapesca ({FLEET_NAME})\n"
        f"  Rango global:     {START_DATE} a {END_DATE}\n"
        f"  Total de fechas:  {total_dates}\n"
        f"  Destino:          {OUTPUT_DIR}\n"
        f"  Una línea por fecha: status (formato/detalle, tamaño, intentos, segundos).\n"
    )

    downloaded_new = 0
    downloaded_old = 0
    skipped = 0
    missing = 0
    processed = 0

    try:
        for fmt_label, start, end, fetcher in ranges:
            print(f"\n--- Rango {fmt_label}: {start} a {end} ---")
            for d in iter_dates(start, end):
                processed += 1
                dest = OUTPUT_DIR / f"{FLEET_NAME}_{d.isoformat()}.csv"
                prefix = f"[{processed:{width}d}/{total_dates}] {d.isoformat()}"

                if dest.exists():
                    skipped += 1
                    print(f"{prefix}  saltado  (ya existía)")
                    continue

                t0 = time.monotonic()
                status, detail, attempts = fetcher(d, dest)
                elapsed = time.monotonic() - t0

                if status == "new":
                    downloaded_new += 1
                    size_mb = dest.stat().st_size / (1024 * 1024)
                    print(
                        f"{prefix}  nuevo    {detail:<11}  "
                        f"{size_mb:5.1f} MB  intentos={attempts}  {elapsed:5.1f}s"
                    )
                elif status == "old":
                    downloaded_old += 1
                    size_mb = dest.stat().st_size / (1024 * 1024)
                    print(
                        f"{prefix}  antiguo  {detail:<11}  "
                        f"{size_mb:5.1f} MB  intentos={attempts}  {elapsed:5.1f}s"
                    )
                else:
                    missing += 1
                    print(
                        f"{prefix}  FALTANTE             "
                        f"             intentos={attempts}  {elapsed:5.1f}s"
                    )
                    if d == today:
                        # El archivo del día se publica a mediodía, así que es
                        # normal que falte si se corre temprano.
                        print(
                            f"  Aviso: {d} aún no publicado en el servidor; "
                            "se completará en una corrida posterior.",
                            file=sys.stderr,
                        )
    except Exception as exc:
        # Limpiar cualquier .tmp dejado por una descarga interrumpida.
        for leftover in OUTPUT_DIR.glob("*.tmp"):
            leftover.unlink(missing_ok=True)
        print(
            "ERROR: la descarga desde Sernapesca falló.\n"
            f"       Detalle: {exc}\n"
            "       Revisa: conexión a internet o si el sitio está temporalmente caído.",
            file=sys.stderr,
        )
        traceback.print_exc()
        sys.exit(2)

    total_bytes = sum(f.stat().st_size for f in OUTPUT_DIR.glob(f"{FLEET_NAME}_*.csv"))
    print(
        "\nResumen final:\n"
        f"  Total de fechas:                 {total_dates}\n"
        f"  Descargados (formato nuevo):     {downloaded_new}\n"
        f"  Descargados (formato antiguo):   {downloaded_old}\n"
        f"  Saltados (ya existían):          {skipped}\n"
        f"  Faltantes (sin archivo):         {missing}\n"
        f"  Tamaño total en {OUTPUT_DIR}: "
        f"{total_bytes / (1024 * 1024):.1f} MB"
    )


if __name__ == "__main__":
    main()
