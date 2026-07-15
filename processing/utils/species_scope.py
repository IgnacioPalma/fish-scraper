"""
Alcance de especies del proyecto — eje ortogonal a `SOURCE`/`REGION`.

El pipeline es, por defecto, jurel-céntrico: retiene solo las recaladas con
captura positiva de JUREL y arrastra una única columna de captura
(`jack_mackerel_tons`). Este eje permite producir, EN PARALELO, un dataset
alternativo con la composición multiespecie de cada zarpe (una columna por
especie), sobre TODAS las recaladas de la flota (no solo las con jurel).

Dos perfiles:
    - `jurel` (por defecto): comportamiento HISTÓRICO idéntico. Filtro por captura
      positiva de JUREL; solo la columna de jurel; slug vacío (rutas y salidas sin
      cambio, sin regresión).
    - `all`: conserva las recaladas con captura positiva de CUALQUIER especie y
      arrastra todas las columnas de especie; anida sus artefactos bajo
      `all_species/` (helper `scoped()`) y sufija el producto final con
      `_all_species` (helper `output_suffix()`).

La flota sigue siendo "solo cerco": el recorte de cerco se aplica aguas abajo al
cruzar la espina de zarpes contra las trazas VMS ya filtradas al registro de
cerco (ver `processing/locations/filter/filter_registry.py`), así que el dataset
`all` queda igualmente acotado a la flota de cerco sin lógica extra.

Cómo se elige el alcance activo:
    Variable de entorno `SPECIES_SCOPE` (en `.env`), por defecto `jurel`. Es
    ortogonal a `SOURCE` y `REGION`; se COMPONE con `SOURCE` en las rutas
    (`species.scoped(source.scoped(base))`) y en el sufijo del producto final.

        SPECIES_SCOPE=all uv run python -m processing.capture.run_pipeline

Requisito de tiempo de ejecución:
    `active_species_scope()` se resuelve en tiempo de ejecución (dentro de
    `main()`), no al importar, para que `run_all.py` pueda alternar
    `SPECIES_SCOPE` en el mismo proceso y correr la cola dependiente una vez por
    cada alcance.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeciesScope:
    """Perfil de un alcance de especies."""
    key: str            # identificador, p.ej. "jurel"
    require_jurel: bool  # True: solo recaladas con jurel > 0; False: cualquier captura > 0
    keep_all_species: bool  # True: arrastra todas las columnas de especie
    slug: str           # segmento de ruta/sufijo; "" para el alcance heredado

    def scoped(self, base: Path) -> Path:
        """Anida `base` bajo el slug del alcance (sin cambios si el slug es vacío).

        Ej.: scoped(data/processing/capture) → data/processing/capture/all_species
        para `all`, y la ruta original para `jurel`."""
        return base / self.slug if self.slug else base

    def output_suffix(self) -> str:
        """Sufijo para el nombre del producto final (p.ej. `_all_species`)."""
        return f"_{self.slug}" if self.slug else ""


SPECIES_SCOPES: dict[str, SpeciesScope] = {
    "jurel": SpeciesScope(key="jurel", require_jurel=True,  keep_all_species=False, slug=""),
    "all":   SpeciesScope(key="all",   require_jurel=False, keep_all_species=True,  slug="all_species"),
}

DEFAULT_SPECIES_SCOPE = "jurel"


def active_species_scope() -> SpeciesScope:
    """Devuelve el alcance de especies activo según `SPECIES_SCOPE`.

    Aborta con un mensaje claro (sin traceback) si no está registrado."""
    key = os.environ.get("SPECIES_SCOPE", DEFAULT_SPECIES_SCOPE).strip().lower()
    if key not in SPECIES_SCOPES:
        sys.exit(
            f"ERROR: SPECIES_SCOPE='{key}' desconocido.\n"
            f"       Opciones válidas: {sorted(SPECIES_SCOPES)}.\n"
            f"       Definí SPECIES_SCOPE en .env (por defecto '{DEFAULT_SPECIES_SCOPE}')."
        )
    return SPECIES_SCOPES[key]
