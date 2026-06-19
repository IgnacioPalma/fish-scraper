"""
Obtiene la lista de Observadores Científicos desde el directorio de
personal del IFOP (https://www.ifop.cl/en/quienes-somos/personal-ifop/).

El directorio se alimenta de un endpoint AJAX que devuelve JSON; lo consultamos
directamente (sin navegador) y filtramos en el cliente por:

    División    = "Investigación Pesquera"
    Departamento= "Gestión de Muestreo"
    Lugar (base)= "TODAS"  (todas las bases; ver BASE más abajo)

El campo "nombres" del directorio viene como "ApellidoPaterno ApellidoMaterno
Nombre(s)"; `dividir_nombre` lo separa en los tres campos que pide el buscador
del SIEM Electrónico (apellido_paterno / apellido_materno / nombre).

Este módulo se usa como librería desde `scrape_siem.py`, pero también puede
ejecutarse directo para inspeccionar a quién se va a buscar:

    uv run python -m processing.ifop.scraper.fetch_personnel
"""

import sys
import unicodedata

import requests


# Endpoint AJAX del directorio de personal (POST, devuelve JSON).
LISTAR_URL = (
    "https://www.ifop.cl/wp-content/themes/ifop-2024-07/"
    "personal_ifop/ajax.php?action=listar"
)

# Filtros pedidos. Se comparan normalizados (sin tildes, minúsculas) para
# resistir variantes de mayúsculas/acentos del directorio.
DIVISION     = "Investigación Pesquera"
DEPARTAMENTO = "Gestión de Muestreo"
# Base (lugar) a incluir. El centinela "TODAS" desactiva el filtro por base y
# trae a los observadores de todas las bases; cualquier otro valor filtra por
# esa base exacta (p.ej. "Coquimbo").
BASE         = "TODAS"

# Cabecera de navegador: el endpoint rechaza peticiones sin User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_TIMEOUT = 30


def normalizar(texto: str) -> str:
    """Minúsculas sin tildes ni espacios sobrantes, para comparar nombres."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    sin_tilde = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_tilde.split()).lower()


def dividir_nombre(nombres: str) -> tuple[str, str, str]:
    """Separa "ApellidoP ApellidoM Nombre(s)" en (paterno, materno, nombre).

    El directorio lista el nombre completo como un solo string en ese orden.
    Se toma el 1.er token como apellido paterno, el 2.º como materno y el resto
    como nombre(s). Si faltan tokens, los campos sobrantes quedan vacíos.
    """
    tokens = nombres.split()
    paterno = tokens[0] if len(tokens) >= 1 else ""
    materno = tokens[1] if len(tokens) >= 2 else ""
    nombre  = " ".join(tokens[2:]) if len(tokens) >= 3 else ""
    return paterno, materno, nombre


def obtener_observadores() -> list[dict]:
    """Devuelve la lista filtrada de observadores (División/Depto/Base).

    Cada elemento es un dict con las claves:
        nombres, cargo, departamento, division, base,
        apellido_paterno, apellido_materno, nombre
    """
    try:
        resp = requests.post(
            LISTAR_URL,
            data={"division": "", "departamento": "", "base": "", "nombres": ""},
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        personal = resp.json()
    except requests.RequestException as exc:
        print(
            f"ERROR: no se pudo consultar el directorio de personal IFOP.\n"
            f"       {exc}\n"
            "       Revisá la conexión a internet o si el endpoint cambió de URL.",
            file=sys.stderr,
        )
        sys.exit(1)
    except ValueError:
        print(
            "ERROR: el directorio de personal no devolvió JSON válido "
            "(¿cambió el endpoint?).",
            file=sys.stderr,
        )
        sys.exit(1)

    div_n  = normalizar(DIVISION)
    dep_n  = normalizar(DEPARTAMENTO)
    base_n = normalizar(BASE)
    # "TODAS" desactiva el filtro por base (se incluyen todas las bases).
    todas_bases = base_n == "todas"

    observadores = []
    for p in personal:
        if (normalizar(p.get("division", "")) == div_n
                and normalizar(p.get("departamento", "")) == dep_n
                and (todas_bases or normalizar(p.get("base", "")) == base_n)):
            paterno, materno, nombre = dividir_nombre(p.get("nombres", ""))
            observadores.append({
                "nombres":          p.get("nombres", "").strip(),
                "cargo":            p.get("cargo", "").strip(),
                "departamento":     p.get("departamento", "").strip(),
                "division":         p.get("division", "").strip(),
                "base":             p.get("base", "").strip(),
                "apellido_paterno": paterno,
                "apellido_materno": materno,
                "nombre":           nombre,
            })

    if not observadores:
        print(
            "ERROR: el filtro no devolvió ningún observador. Verificá que los\n"
            f"       valores DIVISION/DEPARTAMENTO/BASE ('{DIVISION}' / "
            f"'{DEPARTAMENTO}' / '{BASE}') sigan existiendo en el directorio.",
            file=sys.stderr,
        )
        sys.exit(1)

    observadores.sort(key=lambda o: normalizar(o["nombres"]))
    return observadores


def main() -> None:
    observadores = obtener_observadores()
    print(f"Observadores en {BASE} / {DEPARTAMENTO} / {DIVISION}: "
          f"{len(observadores)}\n")
    for o in observadores:
        print(f"  - {o['nombres']}  ({o['cargo']})")
        print(f"      paterno={o['apellido_paterno']!r}  "
              f"materno={o['apellido_materno']!r}  nombre={o['nombre']!r}")


if __name__ == "__main__":
    main()
