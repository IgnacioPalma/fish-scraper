# Pipeline de registro

Descarga el registro **nacional** de embarcaciones LANCHA desde el Registro
Público de Sernapesca, lo **recorta a la región del proyecto** (perfil de región
activo, `processing/utils/regions.py`, elegido por la variable de entorno
`REGION`) y, etapa por etapa, lo reduce a la **flota de cerco de JUREL con señal
de llamada**, enriquecida con los identificadores de IFOP (`vessel_code`,
`cod_barco`) y el arte de pesca de Sernapesca. Todo vive bajo
`data/processing/registry/`.

> **Cambio de origen del dato.** Antes el pipeline arrancaba de un
> `input/register.csv` cargado a mano y ya pre-filtrado a Atacama. Ahora el crudo
> es **nacional** y lo produce el scraper de la etapa 1; el recorte a la región lo
> hace la etapa 3. Así, cambiar `REGION` cambia el alcance sin reemplazar archivos
> a mano. (Validado: el scrape de la III Región LANCHA reproduce exactamente el
> conjunto de 348 RPAs del antiguo `input/register.csv`.)

## Ejecutar el pipeline completo

```bash
uv run python -m processing.registry.run_pipeline
# Saltarse el scraping de Sernapesca (etapas 1 y 6, lentas con red: el listado
# nacional y la consulta por RPA). Reutiliza raw/register.csv y
# fishing_types/register.csv existentes:
uv run python -m processing.registry.run_pipeline --skip-scrape
```

Cada etapa también se puede correr por separado (ver abajo).

## Etapas

| # | Módulo | Entrada | Salida |
|---|---|---|---|
| 1 | `scraper.scrape_registry` | Sernapesca (16 regiones, LANCHA) | `raw/register.csv` (nacional, + `Region`) |
| 2 | `cleaning.clean_register` | `raw/register.csv` | `cleaned/register.csv` |
| 3 | `region_filter.filter_region_scope` | `cleaned/register.csv` | `region_scoped/register.csv` |
| 4 | `filter.filter_register` | `region_scoped/register.csv` | `filtered/register.csv` |
| 5 | `ifop_matching.match_ifop_vessels` | `filtered/register.csv` + `../ifop/vessels.csv` | `ifop_matched/register.csv` |
| 6 | `fishing_types.scrape_fishing_types` | `ifop_matched/register.csv` + Sernapesca | `fishing_types/register.csv` + `fishing_types/fishing_types.csv` |
| 7 | `cerco_filter.filter_cerco` | `fishing_types/register.csv` | `register.csv` (final) |

Recuentos de referencia (REGION=atacama): nacional 14 202 → cleaned 8 543 →
III Región 190 → LANCHA 190 → … → **flota de cerco final**.

### 1. Scraper nacional — `scraper/`

`scrape_registry.py` recorre las 16 regiones costeras del Registro Público de
Sernapesca con la búsqueda **Avanzada** (`Categoría = LANCHA`), parsea la tabla de
resultados (las 19 columnas del registro histórico) y le agrega la columna
`Region` (código romano). Es idempotente: cachea cada región en
`raw/by_region/region_<N>.csv` y reanuda las que falten; concatena todo en
`raw/register.csv`.

```bash
uv run python -m processing.registry.scraper.scrape_registry
```

### 2. Limpieza — `cleaning/`

`clean_register.py` renombra todas las columnas a inglés (`Correlativo`→`id`,
`Nº RPA`→`RPA`, `Nº Matrícula`→`registration_number`, …), pasa `registration_date`
a ISO 8601, descarta columnas no usadas (`Puerto`, `Venc. Matríc`, `Tipo`, `Rut
Armador`, `Nombre Armador`, `Oficina`), **conserva `Region`→`region`** y deduplica
conservando, por `(Nº Matrícula, Puerto)`, la inscripción más reciente. La dedup
usa `Puerto` **antes** de descartarlo (la matrícula sola se reutiliza entre
puertos).

```bash
uv run python -m processing.registry.cleaning.clean_register
```

### 3. Recorte a la región — `region_filter/`

`filter_region_scope.py` conserva solo las filas cuya `region` está en
`registry_region_codes` del perfil de región activo (p.ej. `atacama` → `III
REGION`; `chile` → no-op). Corre **antes** del scraping por RPA de la etapa 6, de
modo que esa consulta cara quede acotada a la región.

```bash
uv run python -m processing.registry.region_filter.filter_region_scope
```

### 4. Filtro por categoría — `filter/`

`filter_register.py` conserva solo `category = LANCHA`, la clase de tamaño de la
flota artesanal relevante.

```bash
uv run python -m processing.registry.filter.filter_register
```

### 5. Emparejamiento IFOP — `ifop_matching/`

`match_ifop_vessels.py` cruza por nombre contra `data/processing/ifop/vessels.csv`
(que ya trae `vessel_code` y `cod_barco`) con coincidencia difusa (`difflib`,
corte `0.85`) más un **guardia de sufijo**: si ambos nombres terminan en un
ordinal distinto se rechaza el par (`ROCIO I` ≠ `ROCIO III`); el caso
sufijo-opcional sí se acepta (`DANIELA ANDREA` ≈ `DANIELA ANDREA I`). Conserva
solo las naves con par en IFOP y añade `vessel_code` y `cod_barco`. Si varias
filas del registro (homónimos / reinscripciones) colapsan en un mismo casco IFOP,
**se descartan todas** (asignación ambigua), dejando un `vessel_code` único por
fila. Imprime las coincidencias difusas, los rechazos por sufijo y los colapsos.

```bash
uv run python -m processing.registry.ifop_matching.match_ifop_vessels
```

### 6. Arte de pesca y señal — `fishing_types/`

`scrape_fishing_types.py` consulta el Registro Público de Sernapesca por cada
`Nº RPA` y extrae la `Señal Distintiva` (`signal_code`, en dígitos puros, sin
prefijo `CA`/`CB`) y los métodos de captura autorizados para **JUREL**. Produce
`fishing_types.csv` (catálogo de artes de JUREL, cada uno con un
`fishing_type_id`) y `register.csv` (columnas del paso 3 más `signal_code` y
`jurel_fishing_type_ids`, ids separados por `|` si la nave usa más de un arte).
El scraping es idempotente: cachea cada RPA en `raw_scrape.csv` y reanuda los que
falten (borra ese archivo para forzar una reconsulta completa).

```bash
uv run python -m processing.registry.fishing_types.scrape_fishing_types
```

### 7. Filtro final — `cerco_filter/`

`filter_cerco.py` conserva las embarcaciones cuyo **único** arte de JUREL es
`CERCO` (id leído de `fishing_types.csv`) **y** que tienen `signal_code` no vacío.
Escribe el producto final del registro en `data/processing/registry/register.csv`.

```bash
uv run python -m processing.registry.cerco_filter.filter_cerco
```

## Notas

- **Convenciones:** todos los CSV usan separador `;`. Docstrings y salida de
  consola en español (ver `../../CLAUDE.md`).
- **Scripts heredados pre-restructuración**, aún apuntando al antiguo
  `register_clean.csv` y no integrados en estas etapas: `enrich_register_ifop.py`
  y `fetch_artes_sernapesca.py` (en la raíz de `processing/registry/`).
