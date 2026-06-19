# Pipeline IFOP

Extrae la actividad de muestreo de los Observadores Científicos (todas las
bases) desde el [SIEM Electrónico de IFOP](https://portal.ifop.cl/siem/) y la
deja como tablas limpias listas para análisis y para cruzar con otras fuentes.

## Ejecutar el pipeline completo

```bash
uv run python -m processing.ifop.run_pipeline
# Reutilizar el CSV crudo existente y saltarse el scraping (lento: abre un
# navegador y recorre el SIEM):
uv run python -m processing.ifop.run_pipeline --skip-scrape
```

Cada etapa también se puede correr por separado (ver abajo).

## Etapas

| # | Módulo | Entrada | Salida |
|---|---|---|---|
| 1 | `scraper.scrape_siem` | directorio de personal IFOP + SIEM | `data/processing/ifop/raw/viajes_observadores.csv` |
| 2 | `cleaning.clean_viajes` | CSV crudo de la etapa 1 | `data/processing/ifop/cleaned/ifop_cleaned.csv` |
| 3 | `identifiers.extract_ports` | CSV limpio de la etapa 2 | `data/processing/ifop/ports.csv` |
| 3 | `identifiers.extract_vessels` | CSV limpio de la etapa 2 | `data/processing/ifop/vessels.csv` |

### 1. Scraping — `processing/ifop/scraper/`

`fetch_personnel.py` obtiene del directorio de personal IFOP la lista de
Observadores Científicos de todas las bases. `scrape_siem.py` busca a cada uno en el
SIEM (Playwright, acceso anónimo) y consolida todos sus viajes en un único CSV
crudo, más un log con el estado del cruce nombre↔SIEM por observador.

Por cada viaje, además, abre la ficha de detalle (el link de la celda "lugar") y
extrae tres campos: `tipo_embarcacion`, `especie_objetivo` y `numero_lances`.
Las fichas no se navegan con el browser sino que se descargan por GET con
`requests` (reutilizando la cookie de sesión del navegador) y en paralelo: un
observador puede tener cientos de viajes, así que navegarlas una a una sería
inviable.

```bash
uv run python -m processing.ifop.scraper.scrape_siem
# Depurar viendo el navegador:  HEADLESS=0 uv run python -m ...
```

### 2. Limpieza — `processing/ifop/cleaning/`

`clean_viajes.py` normaliza el CSV crudo: nombres de columna en inglés, `lugar`
→ booleano `embarked`, fechas a ISO 8601, y separa `cod_barco` / `puerto_*` /
`especie_objetivo` en sus partes `<id>` + `<nombre>`. Mapea también los campos de
la ficha de detalle: `tipo_embarcacion` → `vessel_type`, `especie_objetivo` →
`target_species_id`/`target_species_name`, `numero_lances` → `num_hauls` (entero).
Descarta las columnas de procedencia del scraping (observador, rut, cargo,
estado/score del cruce).

```bash
uv run python -m processing.ifop.cleaning.clean_viajes
```

### 3. Tablas de identificadores — `processing/ifop/identifiers/`

A partir del CSV limpio:

- `extract_ports.py` → `ports.csv` (`port_id`, `port_name`), una fila por puerto.
- `extract_vessels.py` → `vessels.csv` (`vessel_code`, `vessel_name`,
  `cod_barco`). El `cod_barco` se deriva con la fórmula
  `COD_BARCO = HEX(vessel_code + 5)`.

```bash
uv run python -m processing.ifop.identifiers.extract_ports
uv run python -m processing.ifop.identifiers.extract_vessels
```
