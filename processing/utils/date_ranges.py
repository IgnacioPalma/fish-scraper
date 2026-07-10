"""
Rango temporal global del proyecto.

Todos los descargadores se restringen a este rango. Cada producto (Copernicus,
Sernapesca, etc.) lo intersecta con su propia disponibilidad antes de
descargar, y los productos que no tienen datos dentro de la ventana terminan
sin error imprimiendo una nota.

Para mover o recortar el rango: editá las dos constantes acá abajo y volvé a
correr el pipeline (`uv run python -m processing.run_all`).
"""

from datetime import date

START_DATE = date(2019, 3, 3)
END_DATE = date(2024, 12, 31)
