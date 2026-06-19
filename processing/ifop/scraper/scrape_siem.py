"""
Recorre los Observadores Científicos (todas las bases; ver `fetch_personnel.py`)
y, para cada uno, busca su actividad de muestreo en el SIEM Electrónico de IFOP
(https://portal.ifop.cl/siem/), consolidando todos los viajes en un único CSV.

Flujo por observador (navegador Playwright, acceso anónimo — el SIEM no pide
credenciales):

  1. Abrir el SIEM; redirige a `ingresar_rut.php`, que tiene un buscador por
     nombre (apellido paterno / materno / nombre).
  2. Buscar SOLO por apellido paterno (rellenar los tres campos vuelve la
     búsqueda demasiado estricta y no devuelve filas). La búsqueda del SIEM es
     un `LIKE 'prefijo%'` sobre la columna paterno y NO tolera caracteres no
     ASCII (la ñ rompe el match). Por eso, si el paterno exacto no devuelve
     filas, se reintenta con variantes (sin tildes, prefijo cortado antes del
     primer carácter no ASCII, prefijo corto) — útil para erratas del directorio
     (Olivarez→Olivares) y para la ñ (Patiño→"Pati"). Una variante solo se adopta
     si la similitud de nombre supera el umbral.
     El SIEM responde con una tabla de coincidencias: una fila por persona con
     `paterno | materno | nombre | [botón Siguiente]`, y el RUT embebido en el
     `onclick` del botón (`validar_rut_muestreador(...,'<rut>')`).
  3. Elegir la fila cuyo nombre completo más se parece al del directorio
     (similitud difflib, sin tildes). Se registran nº de coincidencias y score.
  4. Pulsar su botón "Siguiente": el SIEM valida el RUT y abre
     `viajes_muestreador.php` con la tabla de viajes del observador.
  5. Leer esa tabla, mapeando por encabezado a las columnas pedidas:
     lugar, fecha_zarpe, fecha_recalada, cod_barco, puerto_zarpe, puerto_recalada.

Salidas:
  data/processing/ifop/raw/viajes_observadores.csv   (CSV unificado)
  data/processing/ifop/raw/scrape_siem_log.csv       (estado por observador)

Uso:
    uv run python -m processing.ifop.scraper.scrape_siem
    # Para depurar viendo el navegador:  HEADLESS=0 uv run python -m ...
"""

import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from processing.ifop.scraper.fetch_personnel import normalizar, obtener_observadores


DATA_DIR   = Path(__file__).resolve().parents[3] / "data"
OUT_DIR    = DATA_DIR / "processing" / "ifop" / "raw"
OUTPUT_CSV = OUT_DIR / "viajes_observadores.csv"
LOG_CSV    = OUT_DIR / "scrape_siem_log.csv"

SIEM_URL = "https://portal.ifop.cl/siem/"

# Mostrar el navegador (HEADLESS=0 para depurar). Por defecto, headless.
HEADLESS = os.environ.get("HEADLESS", "1") not in ("0", "false", "False")

# Tiempos de espera (ms) y cortesía entre observadores.
NAV_TIMEOUT_MS = 60_000
ESPERA_MS      = 3_000
PAUSA_MS       = 1_000

# Score mínimo de similitud de nombre para considerar el match "bueno".
SCORE_OK = 0.80

# Encabezados del SIEM → columnas pedidas (se comparan normalizados).
COLUMNAS = {
    "lugar":           "lugar",
    "fecha zarpe":     "fecha_zarpe",
    "fecha recalada":  "fecha_recalada",
    "cod. barco":      "cod_barco",
    "cod barco":       "cod_barco",
    "puerto zarpe":    "puerto_zarpe",
    "puerto recalada": "puerto_recalada",
}
COLS_SALIDA = ["lugar", "fecha_zarpe", "fecha_recalada",
               "cod_barco", "puerto_zarpe", "puerto_recalada"]

_RE_RUT = re.compile(r",\s*'(\d+)'\s*\)")


def _buscar_coincidencias(page, apellido_paterno: str) -> list[dict]:
    """Busca por apellido paterno y devuelve las filas de coincidencia.

    Cada dict: {paterno, materno, nombre, rut}.
    """
    page.goto(SIEM_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
    page.fill("#apellido_parterno", apellido_paterno)
    page.fill("#apellido_materno", "")
    page.fill("#nombre", "")
    page.click("input[value='Buscar']")
    page.wait_for_timeout(ESPERA_MS)

    # Cada fila de resultado tiene un <input value="Siguiente"> con el RUT en
    # su onclick. (El botón del flujo por RUT es un <button>, no un <input>, así
    # que este selector aísla solo las coincidencias por nombre.)
    return page.eval_on_selector_all(
        "input[value='Siguiente']",
        """els => els.map(e => {
            const celdas = Array.from(e.closest('tr').querySelectorAll('td'))
                                .map(td => td.innerText.trim());
            const m = (e.getAttribute('onclick') || '').match(/,\\s*'(\\d+)'\\s*\\)/);
            return {
                paterno: celdas[0] || '',
                materno: celdas[1] || '',
                nombre:  celdas[2] || '',
                rut:     m ? m[1] : '',
            };
        })""",
    )


def _generar_consultas(apellido_paterno: str) -> list[str]:
    """Variantes de búsqueda del paterno, de la más a la menos específica.

    Orden: exacto → sin tildes → prefijo cortado antes del 1.er carácter no
    ASCII (caso ñ, p.ej. Patiño→"pati") → prefijo corto sin tildes (erratas de
    sufijo, p.ej. Olivarez→"oliva"). Se eliminan duplicados y variantes < 3
    caracteres (demasiado genéricas).
    """
    consultas = [apellido_paterno]

    de = normalizar(apellido_paterno)            # minúsculas, sin tildes ni ñ
    consultas.append(de)

    # Prefijo hasta el primer carácter no ASCII del original (ñ, í, ...).
    corte = next((i for i, ch in enumerate(apellido_paterno) if ord(ch) > 127),
                 len(apellido_paterno))
    consultas.append(normalizar(apellido_paterno[:corte]))

    # Prefijo corto sin tildes (recupera erratas en el sufijo).
    consultas.append(de[:5])

    vistos, salida = set(), []
    for q in consultas:
        q = q.strip()
        if len(q) >= 3 and q not in vistos:
            vistos.add(q)
            salida.append(q)
    return salida


def _click_siguiente(page, rut: str) -> bool:
    """Pulsa el botón "Siguiente" de la fila cuyo onclick lleva ese RUT."""
    for btn in page.query_selector_all("input[value='Siguiente']"):
        if rut in (btn.get_attribute("onclick") or ""):
            btn.click()
            return True
    return False


def _elegir_mejor(coincidencias: list[dict], obs: dict) -> tuple[dict | None, float]:
    """Devuelve (mejor_coincidencia, score) por similitud de nombre completo."""
    objetivo = normalizar(f"{obs['apellido_paterno']} "
                          f"{obs['apellido_materno']} {obs['nombre']}")
    mejor, mejor_score = None, -1.0
    for c in coincidencias:
        cand = normalizar(f"{c['paterno']} {c['materno']} {c['nombre']}")
        score = SequenceMatcher(None, objetivo, cand).ratio()
        if score > mejor_score:
            mejor, mejor_score = c, score
    return mejor, mejor_score


def _leer_tabla_viajes(page) -> list[dict]:
    """Lee viajes_muestreador.php y devuelve filas con las columnas pedidas."""
    filas = page.eval_on_selector_all(
        "table tr",
        """trs => trs.map(tr => {
            const ths = Array.from(tr.querySelectorAll('th')).map(t => t.innerText.trim());
            const tds = Array.from(tr.querySelectorAll('td')).map(t => t.innerText.trim());
            return {ths, tds};
        })""",
    )
    # Localizar la fila de encabezado y construir el mapeo índice → columna.
    indice_col: dict[int, str] = {}
    for f in filas:
        if f["ths"]:
            for i, h in enumerate(f["ths"]):
                clave = COLUMNAS.get(normalizar(h))
                if clave:
                    indice_col[i] = clave
            break
    if not indice_col:
        return []

    salida = []
    for f in filas:
        tds = f["tds"]
        # Saltar la fila-leyenda y cualquier fila sin suficientes celdas.
        if len(tds) <= max(indice_col):
            continue
        fila = {col: tds[i] for i, col in indice_col.items()}
        # Una fila de datos válida tiene al menos fecha de zarpe o barco.
        if not (fila.get("fecha_zarpe") or fila.get("cod_barco")):
            continue
        salida.append(fila)
    return salida


def _scrape_observador(page, obs: dict) -> tuple[list[dict], dict]:
    """Procesa un observador. Devuelve (filas_de_viaje, fila_de_log)."""
    nombre_dir = obs["nombres"]
    log = {
        "observador": nombre_dir, "cargo": obs["cargo"],
        "apellido_paterno": obs["apellido_paterno"],
        "consulta": "", "n_coincidencias": 0, "rut_elegido": "",
        "nombre_siem": "", "score": "", "n_viajes": 0, "estado": "",
    }

    # Probar variantes del paterno; quedarse con la de mayor similitud de
    # nombre. Cortar en cuanto una variante supere el umbral (la exacta suele
    # bastar); si ninguna lo supera, se conserva la mejor de todas.
    mejor = None  # (score, coincidencia, consulta, n_coincidencias)
    for consulta in _generar_consultas(obs["apellido_paterno"]):
        coincidencias = _buscar_coincidencias(page, consulta)
        if not coincidencias:
            continue
        cand, score = _elegir_mejor(coincidencias, obs)
        if mejor is None or score > mejor[0]:
            mejor = (score, cand, consulta, len(coincidencias))
        if score >= SCORE_OK:
            break

    if mejor is None:
        log["estado"] = "sin_match"
        return [], log

    score, cand, consulta, n_coinc = mejor
    log["consulta"] = consulta
    log["n_coincidencias"] = n_coinc
    log["rut_elegido"] = cand["rut"]
    log["nombre_siem"] = f"{cand['paterno']} {cand['materno']} {cand['nombre']}".strip()
    log["score"] = round(score, 3)
    log["estado"] = "match" if score >= SCORE_OK else "match_dudoso"

    # Reejecutar la consulta ganadora para refrescar el DOM y clicar por RUT
    # el botón "Siguiente" de la coincidencia elegida → viajes_muestreador.
    _buscar_coincidencias(page, consulta)
    if not _click_siguiente(page, cand["rut"]):
        log["estado"] = "no_se_pudo_seleccionar"
        return [], log
    page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
    page.wait_for_timeout(ESPERA_MS)

    if "viajes_muestreador" not in page.url:
        log["estado"] = "sin_tabla_viajes"
        return [], log

    viajes = _leer_tabla_viajes(page)
    for v in viajes:
        v["observador"] = nombre_dir
        v["rut"] = cand["rut"]
        v["cargo"] = obs["cargo"]
        # Marca inline la calidad del cruce nombre↔SIEM: las filas
        # "match_dudoso" pueden pertenecer a un homónimo (score bajo) — no se
        # descartan, pero quedan señaladas para revisión aguas abajo.
        v["estado_match"] = log["estado"]
        v["score_match"] = log["score"]
    log["n_viajes"] = len(viajes)
    return viajes, log


def main() -> None:
    observadores = obtener_observadores()
    print(f"Observadores a buscar en el SIEM: {len(observadores)} "
          f"({'headless' if HEADLESS else 'con navegador visible'})\n")

    todas_filas: list[dict] = []
    log_filas: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_context().new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)

        for i, obs in enumerate(observadores, 1):
            print(f"[{i}/{len(observadores)}] {obs['nombres']} ... ", end="", flush=True)
            try:
                viajes, log = _scrape_observador(page, obs)
            except (PWTimeout, Exception) as exc:  # noqa: BLE001 — un fallo no aborta la corrida
                log = {
                    "observador": obs["nombres"], "cargo": obs["cargo"],
                    "apellido_paterno": obs["apellido_paterno"],
                    "n_coincidencias": "", "rut_elegido": "", "nombre_siem": "",
                    "score": "", "n_viajes": 0, "estado": f"error: {exc}"[:120],
                }
                viajes = []
            todas_filas.extend(viajes)
            log_filas.append(log)
            print(f"{log['estado']}  (viajes: {log['n_viajes']})")
            page.wait_for_timeout(PAUSA_MS)

        browser.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cols = COLS_SALIDA + ["observador", "rut", "cargo", "estado_match", "score_match"]
    df = pd.DataFrame(todas_filas, columns=cols)
    df.to_csv(OUTPUT_CSV, index=False)

    log_df = pd.DataFrame(log_filas)
    log_df.to_csv(LOG_CSV, index=False)

    n_ok = int((log_df["estado"] == "match").sum())
    print(f"\nViajes totales: {len(df)} de {len(observadores)} observadores.")
    print(log_df["estado"].value_counts().to_string())
    print(f"\n→ {OUTPUT_CSV}")
    print(f"→ {LOG_CSV}")
    if n_ok < len(observadores):
        print("  (revisá scrape_siem_log.csv: hay observadores sin_match / "
              "match_dudoso / error)")


if __name__ == "__main__":
    main()
