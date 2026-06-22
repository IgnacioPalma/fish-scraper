"""
Registro nacional de embarcaciones LANCHA (paso 0 del pipeline registry).

Descarga el listado de embarcaciones de categoría LANCHA de TODAS las regiones
costeras desde el Registro Público de Sernapesca y arma un registro nacional. Es
el reemplazo del antiguo `input/register.csv` (que venía pre-filtrado a Atacama):
ahora el archivo crudo es nacional y el recorte a la región del proyecto lo hace
la etapa `region_filter` aguas abajo, según el perfil de región activo
(processing/utils/regions.py).

Fuente (consulta pública, sin credenciales):
  https://registropublico.sernapesca.cl/reportes/regembarcaciones_publico/

Flujo por región (búsqueda "Avanzada" del formulario "mantenedor" PHP):
  1. GET  index.php            → token de sesión (campo oculto `session`).
  2. POST mantenedor/guardar.php (búsqueda Avanzada = `campo_t_busqueda=2`,
     `campo_form_region=<N>`, `campo_form_categoria=3` LANCHA, resto en sus
     valores por defecto) → responde con `location = buscarAction.php?...`.
  3. GET  buscarAction.php     → la tabla COMPLETA de resultados (sin paginación
     ni AJAX) con las mismas 19 columnas del registro histórico. Se le agrega la
     columna `Region` (el código romano de la región consultada).

Importante (descubierto al inspeccionar el formulario): la búsqueda Avanzada exige
enviar TODOS los campos del formulario con sus valores por defecto; si faltan,
el stored procedure de Sernapesca falla con un "User Warning" SQL. Por eso se
manda el set completo `_ADVANCED_DEFAULTS` y solo se sobre-escriben región y
categoría. La Región Metropolitana (13) no aparece en el selector (sin costa) y
queda excluida.

Salidas (en data/processing/registry/raw/):
  - by_region/region_<N>.csv : caché idempotente, una región por archivo.
  - register.csv             : concatenación nacional (las 19 columnas + Region).

El scraping es idempotente: cachea cada región y reanuda las que falten. Borrá
`by_region/` (o una región puntual) para forzar una reconsulta.

Uso:
    uv run python -m processing.registry.scraper.scrape_registry
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
OUT_DIR = DATA_DIR / "processing" / "registry" / "raw"
BY_REGION_DIR = OUT_DIR / "by_region"
OUTPUT_CSV = OUT_DIR / "register.csv"

BASE = "https://registropublico.sernapesca.cl"
INDEX_URL = f"{BASE}/reportes/regembarcaciones_publico/index.php"
GUARDAR_URL = f"{BASE}/mantenedor/guardar.php?ref=/reportes/regembarcaciones_publico/index.php"

USER_AGENT = "Mozilla/5.0 (compatible; sst-atacama-research/1.0)"
PAUSA_SEG = 1.0  # cortesía entre regiones
REINTENTOS = 3

# Regiones costeras: valor del selector `campo_form_region` → código romano.
# La RM (valor 13) no figura en el selector (sin litoral) y queda fuera.
REGION_CODES: dict[str, str] = {
    "1": "I REGION", "2": "II REGION", "3": "III REGION", "4": "IV REGION",
    "5": "V REGION", "6": "VI REGION", "7": "VII REGION", "8": "VIII REGION",
    "9": "IX REGION", "10": "X REGION", "11": "XI REGION", "12": "XII REGION",
    "14": "XIV REGION", "15": "XV REGION", "16": "XVI REGION",
}

CATEGORIA_LANCHA = "3"

# Las 19 columnas de la tabla de resultados, en orden (idénticas al registro
# histórico). El header se valida contra esto al parsear.
HEADERS = [
    "Correlativo", "Nº RPA", "Nombre Embarcación", "Categoría", "Fecha Inscripción",
    "Nº Matrícula", "Puerto", "Venc. Matríc", "Tipo", "Rut Armador", "Nombre Armador",
    "Eslora", "Manga", "Puntal", "T.R.G", "Potencia", "Bodega", "Oficina", "Caleta",
]
N_COLS = len(HEADERS)

# Set completo de campos de la búsqueda Avanzada con sus valores por defecto.
# Se sobre-escriben `campo_form_region` y `campo_form_categoria` por consulta.
_ADVANCED_DEFAULTS = {
    "campo_t_busqueda": "2",  # Avanzada
    "campo_t_filtro": "1",
    "campo_form_numero": "", "campo_form_nombre_embarcacion": "", "campo_form_rut": "",
    "campo_form_nombre_armador": "", "campo_form_matricula": "", "campo_form_matricula_puerto": "",
    "campo_form_capacidad_desde": "", "campo_form_capacidad_hasta": "",
    "campo_form_fecha_inscripcion": "", "campo_form_vencimiento_matricula": "",
    "campo_form_vencimiento_contrato": "",
    "campo_form_tgr_desde": "", "campo_form_tgr_hasta": "",
    "campo_form_eslora_desde": "", "campo_form_eslora_hasta": "",
    "campo_form_region": "",          # ← override por región
    "campo_form_oficina": "-1", "campo_form_caleta": "",
    "campo_form_tipo": "-1", "campo_form_categoria": "-1",  # ← override = LANCHA
    "campo_form_arte": "", "campo_form_especie": "-1", "campo_form_estado": "-1",
    "campo_form_tipo_armador": "-1", "campo_form_tipo_catpuertos": "-1",
}

SESSION_RE = re.compile(r'name="session"\s+value="([^"]+)"')
LOCATION_RE = re.compile(r"location\s*=\s*'([^']*buscarAction\.php[^']*)'")
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _abrir(opener: urllib.request.OpenerDirector, url: str, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _limpiar(celda: str) -> str:
    return TAG_RE.sub("", celda).replace("&nbsp;", " ").strip()


def consultar_region(opener: urllib.request.OpenerDirector, region_value: str) -> pd.DataFrame:
    """Devuelve el DataFrame de LANCHAs de una región (19 columnas + Region)."""
    index_html = _abrir(opener, INDEX_URL)
    m = SESSION_RE.search(index_html)
    if not m:
        raise RuntimeError("no se encontró el token de sesión en index.php")

    fields = dict(_ADVANCED_DEFAULTS)
    fields["session"] = m.group(1)
    fields["campo_form_region"] = region_value
    fields["campo_form_categoria"] = CATEGORIA_LANCHA
    payload = urllib.parse.urlencode(fields).encode("utf-8")

    guardar_html = _abrir(opener, GUARDAR_URL, data=payload)
    loc = LOCATION_RE.search(guardar_html)
    if not loc:
        raise RuntimeError("guardar.php no devolvió una location buscarAction.php")

    res = _abrir(opener, BASE + loc.group(1))
    if "Error al ejecutar" in res:
        raise RuntimeError("el stored procedure devolvió un error SQL (¿faltan campos?)")

    label = REGION_CODES[region_value]
    filas = []
    for r in ROW_RE.findall(res):
        celdas = CELL_RE.findall(r)
        if len(celdas) >= N_COLS:
            valores = [_limpiar(c) for c in celdas[:N_COLS]]
            fila = dict(zip(HEADERS, valores))
            fila["Region"] = label
            filas.append(fila)
    return pd.DataFrame(filas, columns=HEADERS + ["Region"])


def _scrape() -> pd.DataFrame:
    """Consulta las regiones que falten respecto al caché por región y concatena."""
    BY_REGION_DIR.mkdir(parents=True, exist_ok=True)

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    cacheadas = {f.stem.replace("region_", "") for f in BY_REGION_DIR.glob("region_*.csv")}
    pendientes = [v for v in REGION_CODES if v not in cacheadas]
    print(f"Regiones en caché: {len(cacheadas)} · a consultar: {len(pendientes)} "
          f"(de {len(REGION_CODES)}).")

    for idx, region_value in enumerate(pendientes, 1):
        label = REGION_CODES[region_value]
        df_region = None
        for intento in range(1, REINTENTOS + 1):
            try:
                df_region = consultar_region(opener, region_value)
                break
            except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
                print(f"  [{label}] intento {intento}/{REINTENTOS} falló: {e}", file=sys.stderr)
                time.sleep(1.5 * intento)
        if df_region is None:
            print(f"  [{label}] sin resultado tras {REINTENTOS} intentos; se omite.",
                  file=sys.stderr)
            continue

        cache_csv = BY_REGION_DIR / f"region_{region_value}.csv"
        df_region.to_csv(cache_csv, sep=";", index=False, encoding="utf-8")
        print(f"[{idx}/{len(pendientes)}] {label:<12} {len(df_region):>5} LANCHAs → {cache_csv.name}")
        time.sleep(PAUSA_SEG)

    # Concatenar todas las regiones presentes en caché.
    partes = [
        pd.read_csv(f, sep=";", dtype=str, encoding="utf-8")
        for f in sorted(BY_REGION_DIR.glob("region_*.csv"))
    ]
    if not partes:
        print("ERROR: no se obtuvo ninguna región.", file=sys.stderr)
        sys.exit(1)
    return pd.concat(partes, ignore_index=True)


def main() -> None:
    nacional = _scrape()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nacional.to_csv(OUTPUT_CSV, sep=";", index=False, encoding="utf-8")

    por_region = nacional["Region"].value_counts()
    print(
        f"\nEmbarcaciones LANCHA (nacional): {len(nacional):,}\n"
        f"Regiones con datos:             {nacional['Region'].nunique()}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )
    print("\nPor región:")
    for label, n in por_region.items():
        print(f"  {label:<12} {n:>5}")


if __name__ == "__main__":
    main()
