"""
Arte de pesca y señal de llamada por embarcación (paso 4 del pipeline registry).

Para cada embarcación de data/processing/registry/ifop_matched/register.csv
consulta su Nº RPA en el Registro Público de Sernapesca y extrae:

  - signal_code            : Señal Distintiva (radio call sign, ej. "CB2428").
  - artes de captura por    : para TODAS las especies que la nave está autorizada a
    especie                  capturar (no solo JUREL), el conjunto de artes (Método
                             de Captura) de cada una. Con esto se puede juzgar el
                             "cerco exclusivo" sobre toda la autorización de la nave,
                             no solo sobre el jurel.

Fuente (consulta pública, sin credenciales):
  https://registropublico.sernapesca.cl/reportes/regembarcaciones_publico/

Flujo por RPA (formulario "mantenedor" PHP con estado en sesión):
  1. GET  index.php            → cookie PHPSESSID + token de sesión.
  2. POST mantenedor/guardar.php (búsqueda Simple, filtro = N° de Inscripción)
                               → responde con `location = buscarAction.php?...`.
  3. GET  buscarAction.php     → ficha con la Señal Distintiva y la tabla de
                                 pesquerías (Método de Captura × Especie).

Salidas (en data/processing/registry/fishing_types/):
  - fishing_types.csv : catálogo de artes observados en CUALQUIER especie, uno por
                        fila con un id numérico (`fishing_type_id`).
  - register.csv      : las mismas columnas de ifop_matched más `signal_code` y
                        `species_fishing_types`: el mapeo especie→artes de la nave,
                        codificado como `ESPECIE:id[,id]|ESPECIE2:id…` (ids del
                        catálogo).

El scraping es idempotente: cachea cada RPA en raw_scrape.csv y reanuda los que
falten. Borra ese archivo para forzar una reconsulta completa. OJO: el esquema del
caché cambió (ahora guarda `species_methods` en vez de `jurel_methods`); si venís
de una versión anterior, borrá raw_scrape.csv para re-consultar de cero.
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


def _encode_species_methods(species_methods: dict[str, set[str]]) -> str:
    """Serializa {especie: {arte,…}} → 'ESPECIE:ARTE1,ARTE2|ESPECIE2:ARTE3'.

    Ordena especies y artes para que la salida sea estable/idempotente.
    """
    partes = []
    for especie in sorted(species_methods):
        artes = ",".join(sorted(species_methods[especie]))
        partes.append(f"{especie}:{artes}")
    return "|".join(partes)


def _decode_species_methods(cell: str) -> dict[str, set[str]]:
    """Inversa de `_encode_species_methods` (tolerante a celdas vacías)."""
    out: dict[str, set[str]] = {}
    for bloque in (cell or "").split("|"):
        if not bloque or ":" not in bloque:
            continue
        especie, artes = bloque.split(":", 1)
        out[especie] = {a for a in artes.split(",") if a}
    return out


def consultar_rpa(opener: urllib.request.OpenerDirector, rpa: str) -> dict:
    """Devuelve {signal_code, species_methods (dict especie→set(artes)), estado}."""
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
        return {"signal_code": "", "species_methods": {}, "estado": ""}

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
    # Se registra el arte de TODAS las especies (no solo JUREL).
    start = next((i for i, c in enumerate(cells) if "todo de Captura" in c), None)
    species_methods: dict[str, set[str]] = {}
    if start is not None:
        i = start + 4
        while i + 3 < len(cells):
            arte, especie, fecha = cells[i], cells[i + 1], cells[i + 2]
            if not FECHA_RE.match(fecha):
                break
            if arte and especie:
                species_methods.setdefault(especie, set()).add(arte)
            i += 4

    return {"signal_code": signal_code, "species_methods": species_methods, "estado": estado}


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
            info = {"signal_code": "", "species_methods": {}, "estado": "ERROR"}

        cache[rpa] = {
            "RPA": rpa,
            "signal_code": info["signal_code"],
            "species_methods": _encode_species_methods(info["species_methods"]),
            "estado": info["estado"],
        }
        n_especies = len(info["species_methods"])
        print(
            f"[{idx}/{len(pendientes)}] {rpa}  señal={info['signal_code'] or '-':<8} "
            f"especies={n_especies}"
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

    # Mapa especie→artes decodificado por RPA (para catálogo y salida).
    raw["_methods"] = raw["species_methods"].fillna("").map(_decode_species_methods)

    # Catálogo de artes vistos en CUALQUIER especie: nombres distintos, id 1..N.
    artes = sorted(
        {arte for m in raw["_methods"] for artes_sp in m.values() for arte in artes_sp}
    )
    lookup = pd.DataFrame(
        {"fishing_type_id": range(1, len(artes) + 1), "fishing_type": artes}
    )
    arte_a_id = dict(zip(lookup["fishing_type"], lookup["fishing_type_id"]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(LOOKUP_CSV, sep=";", index=False, encoding="utf-8")

    # Mapeo especie→ids de arte por RPA: 'ESPECIE:id[,id]|ESPECIE2:id…'.
    def _species_ids(m: dict[str, set[str]]) -> str:
        partes = []
        for especie in sorted(m):
            ids = sorted(arte_a_id[arte] for arte in m[especie])
            partes.append(f"{especie}:{','.join(str(i) for i in ids)}")
        return "|".join(partes)

    raw["species_fishing_types"] = raw["_methods"].map(_species_ids)

    # Señal de llamada en dígitos puros: se descarta el prefijo CA/CB y los
    # separadores (espacio/guion), p. ej. "CB-4352" → "4352", "CA 8189" → "8189".
    # Los valores sin dígitos (p. ej. "SUST." en naves sustituidas) quedan vacíos.
    raw["signal_code"] = raw["signal_code"].fillna("").str.replace(r"\D", "", regex=True)

    enriquecido = ifop.merge(
        raw[["RPA", "signal_code", "species_fishing_types"]], on="RPA", how="left"
    )
    enriquecido.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    con_arte = int((raw["species_fishing_types"] != "").sum())
    con_senal = int((raw["signal_code"].fillna("") != "").sum())
    print(
        f"\nEmbarcaciones:                 {len(ifop):,}\n"
        f"  con señal de llamada:        {con_senal:,}\n"
        f"  con arte(s) (alguna especie):{con_arte:,}\n"
        f"Artes distintos (toda especie):{len(artes)}  → {LOOKUP_CSV}\n"
        f"Archivo escrito:               {OUTPUT_CSV}"
    )
    if artes:
        print("\nCatálogo de artes (fishing_type_id → fishing_type):")
        for _, r in lookup.iterrows():
            print(f"  {r['fishing_type_id']:>2}  {r['fishing_type']}")


if __name__ == "__main__":
    main()
