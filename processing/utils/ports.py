"""
Puerto(s) de interés del proyecto.

Fuente de verdad única para filtrar registros por puerto de desembarque.
Para cambiar el/los puerto(s), editá solo estas constantes.
"""

PORT_OF_INTEREST = "Caldera"

# Puertos de la Región de Atacama (III), tal como aparecen en el catálogo de
# puertos del SIEM IFOP (mayúsculas, sin tildes). Fuente única para filtrar a la
# región de estudio. Se comparan normalizados (ver consumidores), así que las
# tildes/variantes de mayúsculas no importan.
ATACAMA_PORT_NAMES = frozenset({
    "CHANARAL",
    "CALDERA",
    "HUASCO",
    "CARRIZAL BAJO",
    "CHANARAL DE ACEITUNO",
})
