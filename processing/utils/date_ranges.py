"""
Rango temporal global del proyecto.

Todos los descargadores se restringen a este rango. Cada producto (Copernicus,
Sernapesca, etc.) lo intersecta con su propia disponibilidad antes de
descargar, y los productos que no tienen datos dentro de la ventana terminan
sin error imprimiendo una nota.

Para mover o recortar el rango: editá las dos constantes acá abajo y
reconstruí la imagen Docker (`docker compose run --rm --build <servicio>`).
"""

from datetime import date


START_DATE = date(2023, 1, 1)
END_DATE = date(2024, 12, 31)
