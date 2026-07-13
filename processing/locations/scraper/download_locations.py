"""
Descarga los reportes diarios VMS de Sernapesca (flota artesanal, código 31)
y los guarda como un CSV por día en data/processing/locations/raw_daily/
(relativo a la raíz del proyecto).

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

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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

# __file__ = processing/locations/scraper/download_locations.py → parents[3] = raíz del proyecto.
OUTPUT_DIR = (
    Path(__file__).resolve().parents[3]
    / "data" / "processing" / "locations" / "raw_daily"
)

REQUEST_TIMEOUT = 30        # segundos por solicitud HTTP
REQUEST_DELAY = 0.5         # segundos entre solicitudes que tocan la red
MAX_RETRIES = 2             # reintentos para errores 5xx / red transitoria

# Marcador central de progreso: se escribe junto a los CSV diarios y se
# sincroniza a R2 con ellos, así cualquiera puede consultar "N/total" sin
# contar archivos. Lo consume la corrida en bucle de GitHub Actions.
PROGRESS_FILE = OUTPUT_DIR / "_vms_progress.json"
PROGRESS_EVERY = 25          # cada cuántas descargas se reescribe el marcador
BUDGET_EXIT_CODE = 75        # código de salida cuando queda trabajo (presupuesto agotado)

# Registro de fechas SIN dato en el servidor (404 definitivo). Un 404 no deja
# archivo, así que sin esto cada corrida re-intenta las mismas fechas faltantes
# —y en el formato antiguo cada intento barre SS=00..59 (~60 requests, ~90 s por
# fecha)—, agotando el presupuesto sin avanzar. Cacheándolas se saltan al instante
# en las corridas siguientes. Se sincroniza a R2 junto con los CSV diarios.
MISSING_FILE = OUTPUT_DIR / "_vms_missing.txt"

# Cursor de reanudación: la frontera contigua de lo ya resuelto (descargado o
# faltante-cacheado). Sin esto, cada corrida re-escanea desde el inicio (barato
# porque salta al instante, pero imprime ~2000 líneas por tanda). Con el cursor
# la corrida arranca en la frontera. Guarda el rango global vigente: si cambia,
# el cursor se invalida y se vuelve a escanear desde el inicio (seguro).
CURSOR_FILE = OUTPUT_DIR / "_vms_cursor.json"


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
    for ss, url in zip(OLD_SS_RANGE, build_old_urls(d), strict=False):
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
    for url, label in zip(new_urls, labels, strict=False):
        attempts += 1
        content = http_get(url)
        time.sleep(REQUEST_DELAY)
        if content is not None:
            save_atomically(content, dest)
            return "new", label, attempts
    return "missing", "", attempts


def _load_missing() -> set[str]:
    """Carga las fechas ISO ya confirmadas como faltantes (404) en corridas previas."""
    if not MISSING_FILE.exists():
        return set()
    return {
        line.strip()
        for line in MISSING_FILE.read_text().splitlines()
        if line.strip()
    }


def _append_missing(iso: str) -> None:
    """Registra (append) una fecha faltante para no re-intentarla en el futuro."""
    with open(MISSING_FILE, "a") as fh:
        fh.write(iso + "\n")


def _load_cursor() -> date | None:
    """Fecha desde la que reanudar el barrido, o None para escanear desde el inicio.

    Solo se honra si el rango global (START/END) coincide con el guardado: si el
    usuario cambió el rango, el cursor deja de ser válido y se re-escanea todo.
    """
    if not CURSOR_FILE.exists():
        return None
    try:
        data = json.loads(CURSOR_FILE.read_text())
        if (data.get("start") != START_DATE.isoformat()
                or data.get("end") != END_DATE.isoformat()):
            return None
        return date.fromisoformat(data["next"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _write_cursor(next_date: date) -> None:
    """Persiste la frontera de reanudación junto con el rango global vigente."""
    payload = {
        "next": next_date.isoformat(),
        "start": START_DATE.isoformat(),
        "end": END_DATE.isoformat(),
    }
    tmp = CURSOR_FILE.with_name(CURSOR_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, CURSOR_FILE)


def _write_progress(total: int, last_date: date | None, complete: bool) -> None:
    """Escribe el marcador central de progreso (JSON durable, se sincroniza a R2).

    `downloaded` cuenta los CSV diarios en disco (acumulativo entre corridas);
    `complete` indica que se recorrieron TODAS las fechas del rango (aunque algunas
    queden sin archivo por ser 404 permanentes).
    """
    done = len(list(OUTPUT_DIR.glob(f"{FLEET_NAME}_*.csv")))
    payload = {
        "total": total,
        "downloaded": done,
        "remaining": max(total - done, 0),
        "last_date": last_date.isoformat() if last_date else None,
        "complete": complete,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    tmp = PROGRESS_FILE.with_name(PROGRESS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    os.replace(tmp, PROGRESS_FILE)
    estado = "completo" if complete else "parcial"
    print(f"  progreso persistente: {done}/{total} días en disco ({estado})")


def main() -> None:
    # Con line-buffering cada print() aparece al instante (la descarga es larga
    # y conviene ver el progreso fecha por fecha sin esperar a que se llene el buffer).
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    parser = argparse.ArgumentParser(
        description="Descarga los reportes VMS diarios de Sernapesca a raw_daily/.",
    )
    parser.add_argument(
        "--max-minutes", type=float, default=0.0,
        help="Presupuesto de tiempo en minutos. Al agotarse, guarda el progreso y "
             f"sale con código {BUDGET_EXIT_CODE} si aún queda trabajo. 0 = sin límite.",
    )
    args = parser.parse_args()
    budget_s = args.max_minutes * 60 if args.max_minutes > 0 else None
    run_start = time.monotonic()

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
    one_day = timedelta(days=1)

    # Reanudación: arrancar en la frontera de lo ya resuelto (si el cursor sigue
    # siendo válido para el rango vigente); si no, escanear desde el inicio. Las
    # fechas contiguas resueltas antes de `resume_from` no se re-escanean.
    timeline_start = ranges[0][1]
    resume_from = max(_load_cursor() or timeline_start, timeline_start)
    prefix_count = min(max((resume_from - timeline_start).days, 0), total_dates)
    frontier = resume_from

    print(
        f"Descargando reportes diarios VMS de Sernapesca ({FLEET_NAME})\n"
        f"  Rango global:     {START_DATE} a {END_DATE}\n"
        f"  Total de fechas:  {total_dates}\n"
        f"  Destino:          {OUTPUT_DIR}\n"
        f"  Una línea por fecha: status (formato/detalle, tamaño, intentos, segundos).\n"
    )
    if prefix_count:
        print(
            f"  Reanudando desde {resume_from.isoformat()} "
            f"({prefix_count}/{total_dates} fechas previas ya resueltas; se omiten del barrido)\n"
        )

    known_missing = _load_missing()
    if known_missing:
        print(f"  Fechas faltantes ya conocidas en total: {len(known_missing)}\n")

    downloaded_new = 0
    downloaded_old = 0
    skipped = 0
    skipped_missing = 0
    missing = 0
    processed = prefix_count
    downloads_since_flush = 0
    last_processed: date | None = None
    stopped_for_budget = False

    try:
        for fmt_label, start, end, fetcher in ranges:
            if stopped_for_budget:
                break
            print(f"\n--- Rango {fmt_label}: {start} a {end} ---")
            for d in iter_dates(max(start, resume_from), end):
                if budget_s is not None and (time.monotonic() - run_start) >= budget_s:
                    stopped_for_budget = True
                    print(
                        f"\n(presupuesto de {args.max_minutes:.0f} min agotado; "
                        "se guarda el progreso y se continúa en otra corrida)"
                    )
                    break

                processed += 1
                last_processed = d
                iso = d.isoformat()
                dest = OUTPUT_DIR / f"{FLEET_NAME}_{iso}.csv"
                prefix = f"[{processed:{width}d}/{total_dates}] {iso}"

                if dest.exists():
                    skipped += 1
                    print(f"{prefix}  saltado  (ya existía)")
                    if d == frontier:
                        frontier = d + one_day
                    continue

                # Fecha ya confirmada sin dato en el servidor: no re-intentar
                # (evita el barrido SS=00..59 de ~90 s en cada corrida).
                if iso in known_missing:
                    skipped_missing += 1
                    print(f"{prefix}  saltado  (faltante conocido)")
                    if d == frontier:
                        frontier = d + one_day
                    continue

                t0 = time.monotonic()
                status, detail, attempts = fetcher(d, dest)
                elapsed = time.monotonic() - t0

                resolved = True
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
                        # normal que falte si se corre temprano; NO se cachea ni
                        # se avanza la frontera (aparecerá en una corrida posterior).
                        print(
                            f"  Aviso: {d} aún no publicado en el servidor; "
                            "se completará en una corrida posterior.",
                            file=sys.stderr,
                        )
                        resolved = False
                    else:
                        # 404 definitivo (una fecha pasada sin reporte): se cachea
                        # para no re-barrer SS=00..59 en cada corrida.
                        known_missing.add(iso)
                        _append_missing(iso)

                # La frontera solo avanza por fechas resueltas y contiguas: así el
                # cursor nunca salta una fecha aún pendiente (p. ej. hoy sin publicar).
                if resolved and d == frontier:
                    frontier = d + one_day

                downloads_since_flush += 1
                if downloads_since_flush >= PROGRESS_EVERY:
                    _write_progress(total_dates, d, complete=False)
                    _write_cursor(frontier)
                    downloads_since_flush = 0
    except Exception as exc:
        # Limpiar cualquier .tmp dejado por una descarga interrumpida.
        for leftover in OUTPUT_DIR.glob("*.tmp"):
            leftover.unlink(missing_ok=True)
        _write_progress(total_dates, last_processed, complete=False)
        _write_cursor(frontier)
        print(
            "ERROR: la descarga desde Sernapesca falló.\n"
            f"       Detalle: {exc}\n"
            "       Revisa: conexión a internet o si el sitio está temporalmente caído.",
            file=sys.stderr,
        )
        traceback.print_exc()
        sys.exit(2)

    complete = not stopped_for_budget
    _write_progress(total_dates, last_processed, complete=complete)
    _write_cursor(frontier)

    total_bytes = sum(f.stat().st_size for f in OUTPUT_DIR.glob(f"{FLEET_NAME}_*.csv"))
    print(
        "\nResumen final:\n"
        f"  Total de fechas:                 {total_dates}\n"
        f"  Descargados (formato nuevo):     {downloaded_new}\n"
        f"  Descargados (formato antiguo):   {downloaded_old}\n"
        f"  Saltados (ya existían):          {skipped}\n"
        f"  Saltados (faltante conocido):    {skipped_missing}\n"
        f"  Faltantes nuevos (404, cacheados): {missing}\n"
        f"  Tamaño total en {OUTPUT_DIR}: "
        f"{total_bytes / (1024 * 1024):.1f} MB"
    )

    # Presupuesto agotado con trabajo pendiente: salir con un código que el bucle
    # de GitHub Actions interpreta como "seguir" (re-despacharse).
    if stopped_for_budget:
        sys.exit(BUDGET_EXIT_CODE)


if __name__ == "__main__":
    main()
