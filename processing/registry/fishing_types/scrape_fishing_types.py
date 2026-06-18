"""
Arte de pesca y señal de llamada por embarcación (paso 4 del pipeline registry).

Para cada embarcación de data/processing/registry/ifop_matched/register.csv
consulta su Nº RPA en el Registro Público de Sernapesca y extrae:

  - signal_code            : Señal Distintiva (radio call sign, ej. "CB2428").
  - métodos de captura JUREL: los artes con que la nave está autorizada a capturar
                             JUREL (la especie de interés del proyecto).

Fuente (consulta pública, sin credenciales):
  https://registropublico.sernapesca.cl/reportes/regembarcaciones_publico/

Flujo por RPA (formulario "mantenedor" PHP con estado en sesión):
  1. GET  index.php            → cookie PHPSESSID + token de sesión.
  2. POST mantenedor/guardar.php (búsqueda Simple, filtro = N° de Inscripción)
                               → responde con `location = buscarAction.php?...`.
  3. GET  buscarAction.php     → ficha con la Señal Distintiva y la tabla de
                                 pesquerías (Método de Captura × Especie).

Salidas (en data/processing/registry/fishing_types/):
  - fishing_types.csv : catálogo de artes de JUREL observados, uno por fila con un
                        id numérico (`fishing_type_id`).
  - register.csv      : las mismas columnas de ifop_matched más `signal_code` y
                        `jurel_fishing_type_ids` (ids del catálogo, separados por
                        '|' si la nave usa más de un arte para JUREL).

El scraping es idempotente: cachea cada RPA en raw_scrape.csv y reanuda los que
falten. Borra ese archivo para forzar una reconsulta completa.
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

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
IFOP_MATCHED_CSV = DATA_DIR / "processing" / "registry" / "ifop_matched" / "register.csv"
OUT_DIR = DATA_DIR / "processing" / "registry" / "fishing_types"
RAW_CACHE_CSV = OUT_DIR / "raw_scrape.csv"
LOOKUP_CSV = OUT_DIR / "fishing_types.csv"
OUTPUT_CSV = OUT_DIR / "register.csv"

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
    """Devuelve {signal_code, jurel_methods (set), estado} para un RPA."""
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
        return {"signal_code": "", "jurel_methods": set(), "estado": ""}

    ficha = _abrir(opener, BASE + loc.group(1))
    ficha = re.sub(r"<script.*?</script>", "", ficha, flags=re.S)
    cells = [_limpiar(c) for c in CELL_RE.findall(ficha)]

    # Estado: encabezados Nº, Fecha, Oficina, Estado → valores 4 celdas después.
    estado = ""
    for i, c in enumerate(cells):
        if c == "Estado" and i + 4 < len(cells):
            estado = cells[i + 4]
            break

    # Señal Distintiva: bloque "Identificación Embarcación" con 5 encabezados
    # (Nº Matricula, Capitania, Nombre Embarcación, Señal Distintiva, Fecha
    # Vencimiento) seguidos de sus 5 valores → el valor está 5 celdas después.
    signal_code = ""
    for i, c in enumerate(cells):
        if "Distintiva" in c and i + 5 < len(cells):
            signal_code = cells[i + 5]
            break

    # Tabla de pesquerías: encabezados "Método de Captura | Especie | Fecha | Tipo".
    start = next((i for i, c in enumerate(cells) if "todo de Captura" in c), None)
    jurel_methods: set[str] = set()
    if start is not None:
        i = start + 4
        while i + 3 < len(cells):
            arte, especie, fecha = cells[i], cells[i + 1], cells[i + 2]
            if not FECHA_RE.match(fecha):
                break
            if ESPECIE_INTERES in especie:
                jurel_methods.add(arte)
            i += 4

    return {"signal_code": signal_code, "jurel_methods": jurel_methods, "estado": estado}


def _scrape(rpas: list[str]) -> pd.DataFrame:
    """Consulta los RPA que falten respecto al caché y devuelve el caché completo."""
    cache: dict[str, dict] = {}
    if RAW_CACHE_CSV.exists():
        prev = pd.read_csv(RAW_CACHE_CSV, sep=";", dtype=str).fillna("")
        cache = {r["RPA"]: r.to_dict() for _, r in prev.iterrows()}
        print(f"Reanudando: {len(cache)} RPA ya en {RAW_CACHE_CSV.name}.")

    pendientes = [r for r in rpas if r not in cache]
    print(f"RPA a consultar: {len(pendientes)} (de {len(rpas)}).")

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    for idx, rpa in enumerate(pendientes, 1):
        info = None
        for intento in range(1, REINTENTOS + 1):
            try:
                info = consultar_rpa(opener, rpa)
                break
            except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
                print(f"  [{rpa}] intento {intento}/{REINTENTOS} falló: {e}", file=sys.stderr)
                time.sleep(1.5 * intento)
        if info is None:
            info = {"signal_code": "", "jurel_methods": set(), "estado": "ERROR"}

        cache[rpa] = {
            "RPA": rpa,
            "signal_code": info["signal_code"],
            "jurel_methods": "|".join(sorted(info["jurel_methods"])),
            "estado": info["estado"],
        }
        print(
            f"[{idx}/{len(pendientes)}] {rpa}  señal={info['signal_code'] or '-':<8} "
            f"jurel=[{cache[rpa]['jurel_methods']}]"
        )
        # Guardado incremental para poder interrumpir/reanudar.
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(cache.values()).to_csv(RAW_CACHE_CSV, sep=";", index=False, encoding="utf-8")
        time.sleep(PAUSA_SEG)

    return pd.DataFrame([cache[r] for r in rpas])


def main() -> None:
    if not IFOP_MATCHED_CSV.exists():
        print(
            f"ERROR: no se encontró {IFOP_MATCHED_CSV}.\n"
            "       Ejecutá primero: uv run python -m "
            "processing.registry.ifop_matching.match_ifop_vessels",
            file=sys.stderr,
        )
        sys.exit(2)

    ifop = pd.read_csv(IFOP_MATCHED_CSV, sep=";", dtype=str)
    rpas = ifop["RPA"].tolist()

    raw = _scrape(rpas)

    # Catálogo de artes de JUREL: nombres distintos ordenados, id 1..N.
    artes = sorted(
        {m for cell in raw["jurel_methods"] for m in cell.split("|") if m}
    )
    lookup = pd.DataFrame(
        {"fishing_type_id": range(1, len(artes) + 1), "fishing_type": artes}
    )
    arte_a_id = dict(zip(lookup["fishing_type"], lookup["fishing_type_id"]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(LOOKUP_CSV, sep=";", index=False, encoding="utf-8")

    # ids de JUREL por RPA (ordenados, separados por '|').
    def _ids(cell: str) -> str:
        ids = sorted(arte_a_id[m] for m in cell.split("|") if m)
        return "|".join(str(i) for i in ids)

    raw["jurel_fishing_type_ids"] = raw["jurel_methods"].map(_ids)

    # Señal de llamada en dígitos puros: se descarta el prefijo CA/CB y los
    # separadores (espacio/guion), p. ej. "CB-4352" → "4352", "CA 8189" → "8189".
    # Los valores sin dígitos (p. ej. "SUST." en naves sustituidas) quedan vacíos.
    raw["signal_code"] = raw["signal_code"].fillna("").str.replace(r"\D", "", regex=True)

    enriquecido = ifop.merge(
        raw[["RPA", "signal_code", "jurel_fishing_type_ids"]], on="RPA", how="left"
    )
    enriquecido.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    con_jurel = int((raw["jurel_fishing_type_ids"] != "").sum())
    con_senal = int((raw["signal_code"].fillna("") != "").sum())
    print(
        f"\nEmbarcaciones:                 {len(ifop):,}\n"
        f"  con señal de llamada:        {con_senal:,}\n"
        f"  con arte(s) de JUREL:        {con_jurel:,}\n"
        f"Artes de JUREL distintos:      {len(artes)}  → {LOOKUP_CSV}\n"
        f"Archivo escrito:               {OUTPUT_CSV}"
    )
    if artes:
        print("\nCatálogo de artes (fishing_type_id → fishing_type):")
        for _, r in lookup.iterrows():
            print(f"  {r['fishing_type_id']:>2}  {r['fishing_type']}")


if __name__ == "__main__":
    main()
