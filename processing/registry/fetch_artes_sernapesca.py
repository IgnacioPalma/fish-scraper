"""
Enriquece el registro de embarcaciones con el ARTE / MÉTODO DE CAPTURA con que
cada nave está inscrita en el Registro Pesquero Artesanal (RPA) de Sernapesca.

El registro limpio (data/processing/registry/register_clean.csv) NO trae el arte de pesca:
"Categoría = LANCHA" es una clase de tamaño, no un arte. El arte vive en el
registro público de embarcaciones de Sernapesca, donde cada nave tiene una lista
de pesquerías autorizadas, una fila por par (Método de Captura × Especie).

Fuente (consulta pública, sin credenciales):
  https://registropublico.sernapesca.cl/reportes/regembarcaciones_publico/

Flujo de scraping por cada Nº RPA (el formulario es un "mantenedor" PHP con
estado en sesión, no un simple GET):
  1. GET  index.php            → cookie PHPSESSID + token de sesión del formulario.
  2. POST mantenedor/guardar.php (búsqueda Simple, filtro = N° de Inscripción)
                               → responde con `location = buscarAction.php?...`.
  3. GET  buscarAction.php     → ficha de la embarcación con la tabla de pesquerías.

De la ficha se extrae el conjunto de artes (todas las pesquerías) y el
subconjunto de artes autorizados específicamente para JUREL.

Salida: data/processing/registry/register_artes.csv (delimitador ';'). Idempotente: si el
CSV ya existe, sólo consulta los RPA que falten y reanuda.
"""

import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
INPUT_CSV = DATA_DIR / "processing" / "registry" / "register_clean.csv"
OUTPUT_CSV = DATA_DIR / "processing" / "registry" / "register_artes.csv"

BASE = "https://registropublico.sernapesca.cl"
INDEX_URL = f"{BASE}/reportes/regembarcaciones_publico/index.php"
GUARDAR_URL = f"{BASE}/mantenedor/guardar.php?ref=/reportes/regembarcaciones_publico/index.php"

USER_AGENT = "Mozilla/5.0 (compatible; sst-atacama-research/1.0)"
ESPECIE_INTERES = "JUREL"
PAUSA_SEG = 0.4  # cortesía entre embarcaciones
REINTENTOS = 3

SESSION_RE = re.compile(r'name="session"\s+value="([^"]+)"')
LOCATION_RE = re.compile(r"location\s*=\s*'([^']*buscarAction\.php[^']*)'")
CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
FECHA_RE = re.compile(r"\d{2}-\d{2}-\d{4}")


def _abrir(opener: urllib.request.OpenerDirector, url: str, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _limpiar(celda: str) -> str:
    return TAG_RE.sub("", celda).replace("&nbsp;", " ").strip()


def consultar_rpa(opener: urllib.request.OpenerDirector, rpa: str) -> dict:
    """Devuelve {estado, artes_todas, artes_jurel, n_pesquerias} para un RPA."""
    index_html = _abrir(opener, INDEX_URL)
    m = SESSION_RE.search(index_html)
    if not m:
        raise RuntimeError("no se encontró el token de sesión en index.php")
    session = m.group(1)

    payload = urllib.parse.urlencode(
        {
            "session": session,
            "campo_t_busqueda": "1",  # búsqueda Simple
            "campo_t_filtro": "1",  # filtro = N° de Inscripción
            "campo_form_numero": str(rpa),
        }
    ).encode("utf-8")
    guardar_html = _abrir(opener, GUARDAR_URL, data=payload)

    loc = LOCATION_RE.search(guardar_html)
    if not loc:
        # Sin resultados o RPA no encontrado.
        return {"estado": "", "artes_todas": "", "artes_jurel": "", "n_pesquerias": 0}

    ficha = _abrir(opener, BASE + loc.group(1))
    ficha = re.sub(r"<script.*?</script>", "", ficha, flags=re.S)
    cells = [_limpiar(c) for c in CELL_RE.findall(ficha)]

    estado = ""
    for i, c in enumerate(cells):
        if c == "Estado" and i + 4 < len(cells):
            estado = cells[i + 4]  # encabezados: Nº, Fecha, Oficina, Estado → valores
            break

    # Tabla de pesquerías: encabezados "Método de Captura | Especie | Fecha | Tipo".
    start = next((i for i, c in enumerate(cells) if "todo de Captura" in c), None)
    artes_jurel: set[str] = set()
    artes_todas: set[str] = set()
    n = 0
    if start is not None:
        i = start + 4
        while i + 3 < len(cells):
            arte, especie, fecha = cells[i], cells[i + 1], cells[i + 2]
            if not FECHA_RE.match(fecha):
                break
            artes_todas.add(arte)
            if ESPECIE_INTERES in especie:
                artes_jurel.add(arte)
            n += 1
            i += 4

    return {
        "estado": estado,
        "artes_todas": "|".join(sorted(artes_todas)),
        "artes_jurel": "|".join(sorted(artes_jurel)),
        "n_pesquerias": n,
    }


def main() -> None:
    if not INPUT_CSV.exists():
        print(
            f"ERROR: no se encontró {INPUT_CSV}.\n"
            "       Genera primero el registro limpio con clean_register.",
            file=sys.stderr,
        )
        sys.exit(2)

    df = pd.read_csv(INPUT_CSV, sep=";", dtype=str, encoding="utf-8")
    # Una consulta por RPA único; conservo el nombre para la salida.
    naves = df[["Nº RPA", "Nombre Embarcación"]].drop_duplicates("Nº RPA")

    ya_hechos: dict[str, dict] = {}
    if OUTPUT_CSV.exists():
        prev = pd.read_csv(OUTPUT_CSV, sep=";", dtype=str, encoding="utf-8")
        ya_hechos = {r["RPA"]: r.to_dict() for _, r in prev.iterrows()}
        print(f"Reanudando: {len(ya_hechos)} RPA ya consultados en {OUTPUT_CSV.name}.")

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    filas = []
    total = len(naves)
    for idx, (_, nave) in enumerate(naves.iterrows(), 1):
        rpa = nave["Nº RPA"]
        nombre = nave["Nombre Embarcación"]
        if rpa in ya_hechos:
            filas.append(ya_hechos[rpa])
            continue

        info = None
        for intento in range(1, REINTENTOS + 1):
            try:
                info = consultar_rpa(opener, rpa)
                break
            except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
                print(f"  [{rpa}] intento {intento}/{REINTENTOS} falló: {e}", file=sys.stderr)
                time.sleep(1.5 * intento)
        if info is None:
            info = {"estado": "ERROR", "artes_todas": "", "artes_jurel": "", "n_pesquerias": ""}

        fila = {"RPA": rpa, "NOMBRE": nombre, **{k.upper(): v for k, v in info.items()}}
        filas.append(fila)
        print(
            f"[{idx}/{total}] {rpa} {nombre:<28} "
            f"jurel=[{info['artes_jurel']}] todas=[{info['artes_todas']}]"
        )

        # Guardado incremental para poder interrumpir/reanudar.
        pd.DataFrame(filas).to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")
        time.sleep(PAUSA_SEG)

    print(f"\nListo. {len(filas)} embarcaciones escritas en {OUTPUT_CSV}.")


if __name__ == "__main__":
    main()
