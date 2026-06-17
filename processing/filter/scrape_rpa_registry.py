"""
Consulta el Registro Público Sernapesca (registropublico.sernapesca.cl)
para cada embarcación en data/filter/vms_near_caldera.csv y recupera:
  - N° de Inscripción (RPA)
  - Señal Distintiva (número de señal de llamada VHF/radio, sin prefijo CB/CA)
  - Nombre propietario (armador)
  - Estado (Activo / Inactivo)

Los resultados se guardan en data/filter/sernapesca_rpa_lookup.csv.
Esta tabla complementa data/filter/register_vms_bridge.csv con datos
obtenidos directamente desde el sistema oficial, incluyendo la señal
de llamada que permite cruzar con la columna "Radio Call Sign (RC)" del VMS.

Uso:
    uv run python -m processing.filter.scrape_rpa_registry

Nota: el script hace una solicitud HTTP por embarcación con pausa de 1 s
entre llamadas. No requiere autenticación.
"""

import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

try:
    import urllib.request
    import urllib.parse
    import http.cookiejar
except ImportError:
    print("ERROR: módulos urllib no disponibles.", file=sys.stderr)
    sys.exit(2)


DATA_DIR   = Path(__file__).resolve().parent.parent.parent / "data"
VMS_CSV    = DATA_DIR / "filter" / "vms_near_caldera.csv"
OUTPUT_CSV = DATA_DIR / "filter" / "sernapesca_rpa_lookup.csv"

BASE_URL   = "https://registropublico.sernapesca.cl"
INDEX_PATH = "/reportes/regembarcaciones_publico/index.php"
GUARDAR_PATH = "/mantenedor/guardar.php"
VER_PATH   = "/reportes/regembarcaciones_publico/verAction.php"

DELAY_S = 1.2  # pausa entre consultas para no saturar el servidor


def _buscar_embarcacion(nombre):
    """
    Crea una sesión fresca y busca el nombre.
    Retorna lista de (rpa_str, nombre_encontrado).
    """
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "Mozilla/5.0 (research/sst_atacama)")]

    # Paso 1: GET index para obtener session token
    resp = opener.open(BASE_URL + INDEX_PATH)
    content = resp.read().decode("latin-1", errors="replace")
    m = re.search(r'<input type="hidden" name="session" value="([^"]+)"', content)
    session_val = m.group(1) if m else ""

    # Paso 2: POST a guardar.php
    data = urllib.parse.urlencode({
        "session": session_val,
        "campo_t_busqueda": "1",
        "campo_t_filtro": "2",
        "campo_form_nombre_embarcacion": nombre,
        "campo_form_tipo": "",
    }).encode()
    resp2 = opener.open(BASE_URL + GUARDAR_PATH + "?ref=" + INDEX_PATH, data)
    js = resp2.read().decode("latin-1", errors="replace")

    m2 = re.search(r"parent\.location = '([^']+)'", js)
    if not m2:
        return [], opener
    buscar_url = BASE_URL + m2.group(1)

    # Paso 3: GET buscarAction para obtener resultados
    resp3 = opener.open(buscar_url)
    html = resp3.read().decode("latin-1", errors="replace")
    filas = re.findall(
        r"verAction\.php\?num=(\d+)[^>]*>\d+</a></td><td>[^<]*<a[^>]*>([^<]+)</a>",
        html,
    )
    return filas, opener


def _ver_embarcacion(opener, rpa):
    """Obtiene Señal Distintiva, propietario y estado para un RPA dado."""
    resp = opener.open(BASE_URL + VER_PATH + f"?num={rpa}")
    html = resp.read().decode("latin-1", errors="replace")

    data = {}

    # Señal Distintiva: buscar patrón <td>Nombre Embarcación value</td><td>señal</td>
    # La estructura real es: headers en fila 1, valores en fila 2 (misma tabla, 6 cols)
    # Usar regex directo sobre el HTML limpio
    senal_m = re.search(
        r"<td[^>]*>[^<]{1,50}</td>\s*<td[^>]*>(\d{3,6})</td>",
        html,
        re.IGNORECASE,
    )
    # También buscar el nombre que precede a la señal
    nombre_senal = re.search(
        r"<td[^>]*>([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ0-9 \-\.]+)</td>\s*<td[^>]*>(\d{3,6})</td>",
        html,
        re.IGNORECASE,
    )
    if nombre_senal:
        data["NOMBRE_REG"]      = nombre_senal.group(1).strip()
        data["SENAL_DISTINTIVA"] = nombre_senal.group(2).strip()

    # Estado
    estado_m = re.search(r"Activo|Inactivo", html, re.IGNORECASE)
    if estado_m:
        data["ESTADO"] = estado_m.group(0)

    # Oficina / caleta
    oficina_m = re.search(r"<td[^>]*>(Caldera|Coquimbo|Antofagasta|Iquique|Arica)</td>", html)
    if oficina_m:
        data["OFICINA"] = oficina_m.group(1)

    # Propietario: secuencia nombre + apellido1 + apellido2 en celdas
    html_clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    html_clean = re.sub(r"<style[^>]*>.*?</style>", "", html_clean, flags=re.DOTALL)
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html_clean, re.DOTALL)
    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells if re.sub(r"<[^>]+>", "", c).strip()]

    idx_prop = next((i for i, c in enumerate(cells) if c in ("Nombres", "NombresApellido Paterno")), -1)
    if idx_prop >= 0 and idx_prop + 3 < len(cells):
        data["PROPIETARIO"] = " ".join(
            p for p in [cells[idx_prop + 1], cells[idx_prop + 2], cells[idx_prop + 3]] if p
        ).strip()

    return data


def main():
    if not VMS_CSV.exists():
        print(f"ERROR: no se encontró {VMS_CSV}.", file=sys.stderr)
        sys.exit(2)

    df_vms = pd.read_csv(VMS_CSV, sep=";", usecols=["Name"], dtype=str)
    nombres_vms = sorted(df_vms["Name"].dropna().unique().tolist())
    print(f"Embarcaciones VMS únicas: {len(nombres_vms)}")

    # Normalizar nombre VMS: quitar sufijos de flota
    re_sufijo = re.compile(r"\s*\([A-Z][A-Z0-9\-]+\)\s*$|\s+LB\s*$")
    nombres_norm = {n: re.sub(r"\s+", " ", re_sufijo.sub("", n)).strip().upper()
                    for n in nombres_vms}

    import difflib
    filas = []
    no_encontrados = []

    for raw, norm in nombres_norm.items():
        time.sleep(DELAY_S)
        try:
            resultados, opener = _buscar_embarcacion(norm)
        except Exception as e:
            print(f"  ERROR buscando '{norm}': {e}", file=sys.stderr)
            resultados, opener = [], None

        if not resultados:
            no_encontrados.append(raw)
            filas.append({
                "VMS_NAME_RAW": raw,
                "VMS_NAME_NORM": norm,
                "RPA": "",
                "NOMBRE_REG": "",
                "SENAL_DISTINTIVA": "",
                "PROPIETARIO": "",
                "ESTADO": "",
                "OFICINA": "",
            })
            print(f"  ✗ {norm}")
            continue

        # Elegir el resultado cuyo nombre más se acerca al buscado
        nombres_encontrados = [r[1].upper() for r in resultados]
        match = difflib.get_close_matches(norm, nombres_encontrados, n=1, cutoff=0.6)
        if match:
            idx_match = nombres_encontrados.index(match[0])
        else:
            idx_match = 0  # tomar primero
        rpa_str, nombre_enc = resultados[idx_match]

        # Obtener detalle del primer resultado
        time.sleep(DELAY_S)
        try:
            detalle = _ver_embarcacion(opener, rpa_str)
        except Exception as e:
            print(f"  ERROR detalle RPA {rpa_str}: {e}", file=sys.stderr)
            detalle = {}

        fila = {
            "VMS_NAME_RAW":     raw,
            "VMS_NAME_NORM":    norm,
            "RPA":              rpa_str,
            "NOMBRE_REG":       nombre_enc,
            "SENAL_DISTINTIVA": detalle.get("SENAL_DISTINTIVA", ""),
            "PROPIETARIO":      detalle.get("PROPIETARIO", ""),
            "ESTADO":           detalle.get("ESTADO", ""),
            "OFICINA":          detalle.get("OFICINA", ""),
        }
        filas.append(fila)
        senal = detalle.get("SENAL_DISTINTIVA", "?")
        print(f"  ✓ {norm} → RPA {rpa_str}  RC {senal}")

    df_out = pd.DataFrame(filas)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_CSV.with_suffix(".tmp")
    df_out.to_csv(tmp, sep=";", index=False, encoding="utf-8")
    os.replace(tmp, OUTPUT_CSV)

    n_ok = (df_out["RPA"] != "").sum()
    print(
        f"\nEncontrados:      {n_ok}/{len(filas)}\n"
        f"No encontrados:   {len(no_encontrados)}\n"
        f"Archivo escrito:  {OUTPUT_CSV}"
    )
    if no_encontrados:
        print("Sin resultado:", no_encontrados)


if __name__ == "__main__":
    main()
