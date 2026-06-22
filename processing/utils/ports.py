"""
Puerto(s) de interés del proyecto — derivados del perfil de región activo.

La fuente de verdad del alcance geográfico es `processing/utils/regions.py`
(elegida por la variable de entorno `REGION`). Este módulo solo expone, con los
nombres históricos, las facetas de puerto del perfil activo para no tocar a sus
consumidores:

  - PORT_OF_INTEREST  → primer puerto de captura del perfil (back-compat).
  - REGION_PORT_NAMES → allow-list de puertos de recalada del perfil (antes
                        ATACAMA_PORT_NAMES). Se comparan normalizados en los
                        consumidores, así que tildes/mayúsculas no importan.

Para cambiar el/los puerto(s), editá el perfil en `regions.py`, no este archivo.
"""

from processing.utils.regions import active_region


_REGION = active_region()

# Primer puerto de captura del perfil (los consumidores que filtran por un único
# puerto siguen usando esta constante).
PORT_OF_INTEREST = _REGION.ports_of_interest[0] if _REGION.ports_of_interest else None

# Allow-list de puertos de recalada de la región activa (antes ATACAMA_PORT_NAMES).
REGION_PORT_NAMES = _REGION.port_names
