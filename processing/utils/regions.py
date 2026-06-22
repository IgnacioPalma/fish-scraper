"""
Región de estudio del proyecto — fuente única de verdad del alcance geográfico.

Análogo espacial de `date_ranges.py` (que centraliza el rango temporal). Toda la
narrowing geográfica del pipeline (bounding box de las grillas Copernicus, recorte
espacial del VMS, allow-list de puertos de recalada, puerto(s) de captura,
región(es) de desembarque y región(es) del registro Sernapesca) sale de UN perfil
de región activo.

Cómo se elige la región activa:
    Variable de entorno `REGION` (en `.env`), por defecto `atacama`. Para correr el
    pipeline sobre otro alcance, cambiá `REGION` sin tocar código:

        REGION=norte_grande uv run python -m processing.registry.run_pipeline
        REGION=chile        uv run python -m processing.run_all

Tipos de región:
    - Hoja (leaf): una de las 15 regiones costeras de Chile, con sus propias
      facetas (bbox, puertos, etc.). Ej.: `atacama`, `biobio`, `magallanes`.
    - Macro-zona (composite): unión de varias hojas. Ej.: `norte_grande`,
      `norte`, `sur`, `chile`. Sus facetas se calculan uniendo las de sus
      miembros (bbox = envolvente; puertos/regiones = unión).

Cómo agregar/ajustar una región:
    Editá la hoja correspondiente en `_LEAVES` (o agregá una macro-zona en
    `_COMPOSITES`). Un perfil junta TODAS las facetas geográficas; elegir el
    nombre arrastra todo lo demás.

Asimetría allow-list ↔ coordenadas (ojo al editar):
    `port_names` (allow-list de recalada IFOP) incluye TODOS los puertos del perfil,
    incluso los que no tienen coordenadas. `port_coords()` (reemplazo de
    `puertos_atacama.json`, usado para asignar el puerto más cercano por distancia)
    devuelve SOLO los puertos con lat/lon. Por eso Atacama lista 5 puertos en la
    allow-list pero 4 en coordenadas (Chañaral de Aceituno va sin coords), igual que
    el JSON histórico — así el comportamiento por defecto queda idéntico.

Cobertura de datos por región (importante):
    - bbox y registry_region_codes: definidos para TODAS las regiones costeras.
    - puertos (nombres + coordenadas): para las regiones distintas de Atacama se
      cargan los PUERTOS PRINCIPALES de pesca (curados a mano). No es un catálogo
      exhaustivo de caletas; ampliá la hoja si necesitás más puertos. El registro
      público de Sernapesca no trae coordenadas, por eso esta lista es curada.
    - landing_region_names: el `data/desembarques.csv` viene con los nombres de
      región acentuados corruptos (mojibake); el filtro de desembarques compara de
      forma tolerante (plegado a ASCII), así que basta el nombre limpio acá.

Inputs pre-filtrados (advertencia):
    Los archivos crudos que aporta el usuario pueden venir ya recortados a una región.
    Como todos los filtros del pipeline son intersectivos, AMPLIAR la región nunca
    rompe (solo trae las filas que existan), pero tampoco inventa datos que el archivo
    no tenga.
"""

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Port:
    """Puerto del perfil. `lat`/`lon` None ⇒ puerto solo-allow-list (sin coordenadas)."""
    name: str                  # nombre tal como aparece en la columna PORT, p.ej. "Caldera"
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class Region:
    """Perfil geográfico completo del proyecto."""
    key: str                                 # identificador, p.ej. "atacama"
    bbox: tuple[float, float, float, float]  # (lat_min, lat_max, lon_min, lon_max)
    ports: tuple[Port, ...]                  # puertos del perfil (con o sin coordenadas)
    ports_of_interest: tuple[str, ...]       # puerto(s) del filtro de captura, p.ej. ("Caldera",)
    landing_region_names: tuple[str, ...]    # región(es) para el filtro de desembarques, p.ej. ("Atacama",)
    registry_region_codes: tuple[str, ...]   # código(s) romanos Sernapesca, p.ej. ("III REGION",)

    @property
    def port_names(self) -> frozenset[str]:
        """Allow-list de recalada: TODOS los puertos del perfil (con o sin coords)."""
        return frozenset(p.name for p in self.ports)

    def port_coords(self) -> list[dict]:
        """Puertos con coordenadas, con la misma forma que el viejo `puertos_atacama.json`.

        Aborta con un mensaje claro si el perfil no define ninguno (ver advertencia
        en el docstring del módulo)."""
        coords = [
            {"nombre": p.name, "latitud": p.lat, "longitud": p.lon}
            for p in self.ports
            if p.lat is not None and p.lon is not None
        ]
        if not coords:
            sys.exit(
                f"ERROR: la región '{self.key}' no tiene coordenadas de puerto definidas.\n"
                f"       Agregá los puertos (con lat/lon) al perfil en "
                f"processing/utils/regions.py, o corré con una región que sí los tenga "
                f"(p.ej. REGION=atacama)."
            )
        return coords


# ---------------------------------------------------------------------------
# Regiones hoja (las 15 regiones costeras de Chile)
#
# bbox = (lat_min, lat_max, lon_min, lon_max), cubre la franja costera de la
# región + ~2° mar adentro. `ports` lista los puertos PRINCIPALES de pesca con
# coordenadas curadas (no exhaustivo). La Región Metropolitana (sin litoral) no
# tiene perfil.
# ---------------------------------------------------------------------------

_LEAVES: dict[str, Region] = {
    "arica": Region(
        key="arica", bbox=(-19.3, -17.5, -71.5, -69.8),
        ports=(Port("Arica", -18.476, -70.323),),
        ports_of_interest=("Arica",),
        landing_region_names=("Arica y Parinacota",),
        registry_region_codes=("XV REGION",),
    ),
    "tarapaca": Region(
        key="tarapaca", bbox=(-21.7, -18.9, -71.5, -69.5),
        ports=(Port("Iquique", -20.214, -70.152), Port("Pisagua", -19.597, -70.213)),
        ports_of_interest=("Iquique", "Pisagua"),
        landing_region_names=("Tarapacá",),
        registry_region_codes=("I REGION",),
    ),
    "antofagasta": Region(
        key="antofagasta", bbox=(-26.1, -20.9, -71.8, -69.5),
        ports=(
            Port("Antofagasta", -23.650, -70.398), Port("Mejillones", -23.099, -70.449),
            Port("Tocopilla", -22.092, -70.199), Port("Taltal", -25.407, -70.484),
        ),
        ports_of_interest=("Antofagasta", "Mejillones", "Tocopilla", "Taltal"),
        landing_region_names=("Antofagasta",),
        registry_region_codes=("II REGION",),
    ),
    # Atacama: reproduce EXACTAMENTE el comportamiento histórico (4 puertos con
    # coords idénticos al viejo puertos_atacama.json + Chañaral de Aceituno solo en
    # la allow-list, sin coords; captura filtrada a Caldera).
    "atacama": Region(
        key="atacama", bbox=(-29.0, -25.0, -72.0, -70.0),
        ports=(
            Port("Caldera", -27.0667, -70.8194),
            Port("Chañaral", -26.3500, -70.6233),
            Port("Huasco", -28.4714, -71.2214),
            Port("Carrizal Bajo", -28.0797, -71.1294),
            Port("Chañaral de Aceituno"),  # solo allow-list (sin coordenadas)
        ),
        ports_of_interest=("Caldera",),
        landing_region_names=("Atacama",),
        registry_region_codes=("III REGION",),
    ),
    "coquimbo": Region(
        key="coquimbo", bbox=(-32.3, -29.0, -72.5, -70.8),
        ports=(
            Port("Coquimbo", -29.953, -71.339), Port("Tongoy", -30.255, -71.496),
            Port("Los Vilos", -31.911, -71.510),
        ),
        ports_of_interest=("Coquimbo", "Tongoy", "Los Vilos"),
        landing_region_names=("Coquimbo",),
        registry_region_codes=("IV REGION",),
    ),
    "valparaiso": Region(
        key="valparaiso", bbox=(-33.7, -32.0, -72.5, -71.2),
        ports=(
            Port("San Antonio", -33.593, -71.621), Port("Valparaíso", -33.036, -71.629),
            Port("Quintero", -32.783, -71.527),
        ),
        ports_of_interest=("San Antonio", "Valparaíso", "Quintero"),
        landing_region_names=("Valparaíso",),
        registry_region_codes=("V REGION",),
    ),
    "ohiggins": Region(
        key="ohiggins", bbox=(-34.6, -33.8, -72.5, -71.6),
        ports=(Port("Pichilemu", -34.388, -72.003),),
        ports_of_interest=("Pichilemu",),
        landing_region_names=("O'Higgins",),
        registry_region_codes=("VI REGION",),
    ),
    "maule": Region(
        key="maule", bbox=(-36.2, -34.6, -73.0, -72.0),
        ports=(Port("Constitución", -35.333, -72.411), Port("Pelluhue", -35.821, -72.581)),
        ports_of_interest=("Constitución", "Pelluhue"),
        landing_region_names=("Maule",),
        registry_region_codes=("VII REGION",),
    ),
    "nuble": Region(
        key="nuble", bbox=(-36.7, -36.0, -73.2, -72.4),
        ports=(Port("Cobquecura", -36.133, -72.794),),
        ports_of_interest=("Cobquecura",),
        landing_region_names=("Ñuble",),
        registry_region_codes=("XVI REGION",),
    ),
    "biobio": Region(
        key="biobio", bbox=(-38.6, -36.5, -74.0, -72.6),
        ports=(
            Port("Talcahuano", -36.724, -73.116), Port("San Vicente", -36.733, -73.166),
            Port("Coronel", -37.028, -73.158), Port("Lota", -37.090, -73.157),
            Port("Lebu", -37.609, -73.652),
        ),
        ports_of_interest=("Talcahuano", "San Vicente", "Coronel", "Lota", "Lebu"),
        landing_region_names=("Bio-bío",),  # skeleton ASCII que calza con desembarques.csv (mojibake)
        registry_region_codes=("VIII REGION",),
    ),
    "araucania": Region(
        key="araucania", bbox=(-39.7, -37.8, -74.0, -73.0),
        ports=(Port("Puerto Saavedra", -38.787, -73.389), Port("Queule", -39.378, -73.219)),
        ports_of_interest=("Puerto Saavedra", "Queule"),
        landing_region_names=("La Araucanía",),
        registry_region_codes=("IX REGION",),
    ),
    "los_rios": Region(
        key="los_rios", bbox=(-40.5, -39.2, -74.2, -73.0),
        ports=(Port("Corral", -39.887, -73.429), Port("Niebla", -39.869, -73.398)),
        ports_of_interest=("Corral", "Niebla"),
        landing_region_names=("Los Ríos",),
        registry_region_codes=("XIV REGION",),
    ),
    "los_lagos": Region(
        key="los_lagos", bbox=(-44.2, -40.2, -75.0, -72.0),
        ports=(
            Port("Puerto Montt", -41.469, -72.942), Port("Calbuco", -41.773, -73.135),
            Port("Ancud", -41.866, -73.830), Port("Quellón", -43.119, -73.621),
        ),
        ports_of_interest=("Puerto Montt", "Calbuco", "Ancud", "Quellón"),
        landing_region_names=("Los Lagos",),
        registry_region_codes=("X REGION",),
    ),
    "aysen": Region(
        key="aysen", bbox=(-49.5, -43.7, -76.0, -72.0),
        ports=(
            Port("Puerto Aysén", -45.403, -72.691), Port("Puerto Chacabuco", -45.464, -72.828),
            Port("Melinka", -43.896, -73.745),
        ),
        ports_of_interest=("Puerto Aysén", "Puerto Chacabuco", "Melinka"),
        landing_region_names=("Aysén",),
        registry_region_codes=("XI REGION",),
    ),
    "magallanes": Region(
        key="magallanes", bbox=(-56.6, -48.5, -76.5, -66.0),
        ports=(Port("Punta Arenas", -53.163, -70.917), Port("Puerto Natales", -51.728, -72.507)),
        ports_of_interest=("Punta Arenas", "Puerto Natales"),
        landing_region_names=("Magallanes",),
        registry_region_codes=("XII REGION",),
    ),
    # Sub-perfil de Atacama: solo el puerto Caldera (el bbox oceánico no cambia).
    "caldera": Region(
        key="caldera", bbox=(-29.0, -25.0, -72.0, -70.0),
        ports=(Port("Caldera", -27.0667, -70.8194),),
        ports_of_interest=("Caldera",),
        landing_region_names=("Atacama",),
        registry_region_codes=("III REGION",),
    ),
}


def _compose(key: str, *member_keys: str) -> Region:
    """Construye una macro-zona uniendo las facetas de sus regiones hoja."""
    members = [_LEAVES[k] for k in member_keys]
    lat_min = min(m.bbox[0] for m in members)
    lat_max = max(m.bbox[1] for m in members)
    lon_min = min(m.bbox[2] for m in members)
    lon_max = max(m.bbox[3] for m in members)

    # Unión de puertos preservando orden y sin duplicar por nombre.
    ports: list[Port] = []
    vistos: set[str] = set()
    for m in members:
        for p in m.ports:
            if p.name not in vistos:
                vistos.add(p.name)
                ports.append(p)

    def _union(attr: str) -> tuple[str, ...]:
        out: list[str] = []
        for m in members:
            for v in getattr(m, attr):
                if v not in out:
                    out.append(v)
        return tuple(out)

    return Region(
        key=key,
        bbox=(lat_min, lat_max, lon_min, lon_max),
        ports=tuple(ports),
        ports_of_interest=_union("ports_of_interest"),
        landing_region_names=_union("landing_region_names"),
        registry_region_codes=_union("registry_region_codes"),
    )


# ---------------------------------------------------------------------------
# Macro-zonas (composites)
# ---------------------------------------------------------------------------

_NORTE_GRANDE = ("arica", "tarapaca", "antofagasta")
_NORTE_CHICO = ("atacama", "coquimbo")
_CENTRO = ("valparaiso", "ohiggins", "maule")
_CENTRO_SUR = ("nuble", "biobio")
_SUR = ("araucania", "los_rios", "los_lagos")
_AUSTRAL = ("aysen", "magallanes")
_TODAS = _NORTE_GRANDE + _NORTE_CHICO + _CENTRO + _CENTRO_SUR + _SUR + _AUSTRAL

_COMPOSITES: dict[str, Region] = {
    "norte_grande": _compose("norte_grande", *_NORTE_GRANDE),
    "norte_chico": _compose("norte_chico", *_NORTE_CHICO),
    "norte": _compose("norte", *_NORTE_GRANDE, *_NORTE_CHICO),
    "centro": _compose("centro", *_CENTRO),
    "centro_sur": _compose("centro_sur", *_CENTRO_SUR),
    "sur": _compose("sur", *_SUR),
    "austral": _compose("austral", *_AUSTRAL),
    "chile": _compose("chile", *_TODAS),
}


REGIONS: dict[str, Region] = {**_LEAVES, **_COMPOSITES}

DEFAULT_REGION = "atacama"


def active_region() -> Region:
    """Devuelve el perfil de región activo según la variable de entorno `REGION`.

    Aborta con un mensaje claro (sin traceback) si `REGION` no está registrada."""
    key = os.environ.get("REGION", DEFAULT_REGION).strip().lower()
    if key not in REGIONS:
        sys.exit(
            f"ERROR: REGION='{key}' desconocida.\n"
            f"       Opciones válidas: {sorted(REGIONS)}.\n"
            f"       Definí REGION en .env (por defecto '{DEFAULT_REGION}')."
        )
    return REGIONS[key]
