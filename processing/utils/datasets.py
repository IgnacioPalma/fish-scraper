"""
Fuente de captura del proyecto — fuente única de verdad del origen de datos.

Análogo de `regions.py` (alcance geográfico) y `date_ranges.py` (rango temporal),
pero para el ORIGEN de la bitácora de captura. El pipeline puede correr sobre dos
insumos distintos y producir dos datasets de modelado comparables:

    - `bitacora` (por defecto): la bitácora IFOP de Atacama artesanal
      (`bitacora.csv`), formato ancho (una columna por especie).
    - `backup`: el respaldo nacional de captura (`backup.csv`), formato largo
      (una fila por especie por lance), flota artesanal + industrial. Se filtra a
      la flota `Artesanal` para que el corte coincida con la bitácora.

Cómo se elige la fuente activa:
    Variable de entorno `SOURCE` (en `.env`), por defecto `bitacora`. Es ortogonal
    a `REGION`: `REGION` gobierna la geografía, `SOURCE` el archivo de entrada.

        SOURCE=backup uv run python -m processing.capture.run_pipeline

Aislamiento de artefactos (importante):
    Para que las dos corridas NO se pisen, cada fuente escribe sus productos
    intermedios y finales en rutas propias:
      - `bitacora` conserva las rutas HISTÓRICAS intactas (slug vacío), así que el
        comportamiento por defecto queda idéntico y sin regresión.
      - `backup` anida sus artefactos bajo un subdirectorio `backup/` (helper
        `scoped()`) y sufija el producto final con `_backup` (helper
        `output_suffix()`).
    Las etapas VMS aguas arriba (raw_daily → raw_consolidated → cleaned → filtered)
    NO dependen de la captura y se comparten entre fuentes: NO se scopean.

Requisito de tiempo de ejecución:
    `active_source()` se resuelve en tiempo de ejecución (dentro de `main()`), no al
    importar el módulo, para que `run_all.py` pueda alternar `SOURCE` en el mismo
    proceso y correr la cola dependiente de la fuente una vez por cada una.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Dataset:
    """Perfil de una fuente de captura."""
    key: str                    # identificador, p.ej. "bitacora"
    input_file: str             # nombre del crudo en data/processing/capture/input/
    fleet: str | None           # filtro de flota (p.ej. "Artesanal"); None = sin filtro
    slug: str                   # segmento de ruta/sufijo; "" para la fuente heredada

    def scoped(self, base: Path) -> Path:
        """Anida `base` bajo el slug de la fuente (sin cambios si el slug es vacío).

        Ej.: scoped(data/processing/capture) → data/processing/capture/backup para
        `backup`, y la ruta original para `bitacora`."""
        return base / self.slug if self.slug else base

    def output_suffix(self) -> str:
        """Sufijo para el nombre del producto final (p.ej. `_backup`)."""
        return f"_{self.slug}" if self.slug else ""


SOURCES: dict[str, Dataset] = {
    "bitacora": Dataset(key="bitacora", input_file="bitacora.csv", fleet=None, slug=""),
    "backup":   Dataset(key="backup",   input_file="backup.csv",   fleet="Artesanal", slug="backup"),
}

DEFAULT_SOURCE = "bitacora"


def active_source() -> Dataset:
    """Devuelve la fuente de captura activa según la variable de entorno `SOURCE`.

    Aborta con un mensaje claro (sin traceback) si `SOURCE` no está registrada."""
    key = os.environ.get("SOURCE", DEFAULT_SOURCE).strip().lower()
    if key not in SOURCES:
        sys.exit(
            f"ERROR: SOURCE='{key}' desconocida.\n"
            f"       Opciones válidas: {sorted(SOURCES)}.\n"
            f"       Definí SOURCE en .env (por defecto '{DEFAULT_SOURCE}')."
        )
    return SOURCES[key]
