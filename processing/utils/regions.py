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

        REGION=caldera uv run python -m processing.capture.run_pipeline

Cómo agregar una región:
    Definí un `Region` nuevo abajo y registralo en `REGIONS`. Un perfil junta TODAS
    las facetas geográficas; elegir el nombre arrastra todo lo demás.

Asimetría allow-list ↔ coordenadas (ojo al editar):
    `port_names` (allow-list de recalada IFOP) incluye TODOS los puertos del perfil,
    incluso los que no tienen coordenadas. `port_coords()` (reemplazo de
    `puertos_atacama.json`, usado para asignar el puerto más cercano por distancia)
    devuelve SOLO los puertos con lat/lon. Por eso Atacama lista 5 puertos en la
    allow-list pero 4 en coordenadas (Chañaral de Aceituno va sin coords), igual que
    el JSON histórico — así el comportamiento por defecto queda idéntico.

Inputs pre-filtrados (advertencia):
    Los archivos crudos que aporta el usuario pueden venir ya recortados a una región.
    Como todos los filtros del pipeline son intersectivos, AMPLIAR la región nunca
    rompe (solo trae las filas que existan), pero tampoco inventa datos que el archivo
    no tenga. El único riesgo real es la lista de coordenadas de puerto: si no calza
    con la región activa, la asignación al puerto más cercano falla en silencio. Por
    eso los perfiles sin coordenadas (CHILE, NORTE_GRANDE) abortan con un mensaje claro
    en `port_coords()` en vez de caer de vuelta a los puertos de Atacama.
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
# Perfiles de región
# ---------------------------------------------------------------------------

# Atacama (III Región): reproduce EXACTAMENTE el comportamiento histórico.
# Los 4 puertos con coordenadas son idénticos al viejo puertos_atacama.json;
# "Chañaral de Aceituno" se suma solo a la allow-list (sin coords), igual que antes.
_ATACAMA = Region(
    key="atacama",
    bbox=(-29.0, -25.0, -72.0, -70.0),
    ports=(
        Port("Caldera", -27.0667, -70.8194),
        Port("Chañaral", -26.3500, -70.6233),
        Port("Huasco", -28.4714, -71.2214),
        Port("Carrizal Bajo", -28.0797, -71.1294),
        Port("Chañaral de Aceituno"),  # solo allow-list (sin coordenadas), como el JSON histórico
    ),
    ports_of_interest=("Caldera",),
    landing_region_names=("Atacama",),
    registry_region_codes=("III REGION",),
)

# Caldera: mismo bounding box oceánico que Atacama, pero recortado al puerto Caldera.
# Desembarques/registro no tienen granularidad sub-regional: Caldera solo acota puertos.
_CALDERA = Region(
    key="caldera",
    bbox=(-29.0, -25.0, -72.0, -70.0),
    ports=(
        Port("Caldera", -27.0667, -70.8194),
    ),
    ports_of_interest=("Caldera",),
    landing_region_names=("Atacama",),
    registry_region_codes=("III REGION",),
)

# --- Stubs (alcance amplio). El registro (scraper + filtro) funciona; los filtros
# basados en puertos NO hasta que se complete `ports`. bbox provisorio. ---

# Norte Grande: XV (Arica y Parinacota), I (Tarapacá), II (Antofagasta).
_NORTE_GRANDE = Region(
    key="norte_grande",
    bbox=(-26.0, -17.5, -72.0, -68.0),  # TODO: ajustar bbox y agregar puertos del Norte Grande
    ports=(),
    ports_of_interest=(),
    landing_region_names=("Arica y Parinacota", "Tarapacá", "Antofagasta"),
    registry_region_codes=("XV REGION", "I REGION", "II REGION"),
)

# Chile entero: las 16 regiones.
_CHILE = Region(
    key="chile",
    bbox=(-56.0, -17.5, -76.0, -66.0),  # TODO: ajustar bbox y agregar puertos nacionales
    ports=(),
    ports_of_interest=(),
    landing_region_names=(),  # TODO: completar nombres de región para desembarques
    registry_region_codes=(
        "XV REGION", "I REGION", "II REGION", "III REGION", "IV REGION",
        "V REGION", "VI REGION", "VII REGION", "VIII REGION", "IX REGION",
        "XIV REGION", "X REGION", "XI REGION", "XII REGION", "RM REGION", "XVI REGION",
    ),
)


REGIONS: dict[str, Region] = {
    "atacama": _ATACAMA,
    "caldera": _CALDERA,
    "norte_grande": _NORTE_GRANDE,
    "chile": _CHILE,
}

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
