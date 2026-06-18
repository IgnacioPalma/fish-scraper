# Pipeline de registro

Toma el registro histórico de embarcaciones de Atacama y, etapa por etapa, lo
reduce a la **flota de cerco de JUREL con señal de llamada**, enriquecida con los
identificadores de IFOP (`vessel_code`, `cod_barco`) y el arte de pesca de
Sernapesca. Todo vive bajo `data/processing/registry/`.

## Ejecutar el pipeline completo

```bash
uv run python -m processing.registry.run_pipeline
# Saltarse el scraping de Sernapesca (etapa 4, lenta: una consulta HTTP por RPA).
# Reutiliza data/processing/registry/fishing_types/register.csv:
uv run python -m processing.registry.run_pipeline --skip-scrape
```

Cada etapa también se puede correr por separado (ver abajo).

## Etapas

| # | Módulo | Entrada | Salida |
|---|---|---|---|
| 1 | `cleaning.clean_register` | `input/register.csv` | `cleaned/register.csv` |
| 2 | `filter.filter_register` | `cleaned/register.csv` | `filtered/register.csv` |
| 3 | `ifop_matching.match_ifop_vessels` | `filtered/register.csv` + `../ifop/vessels.csv` | `ifop_matched/register.csv` |
| 4 | `fishing_types.scrape_fishing_types` | `ifop_matched/register.csv` + Sernapesca | `fishing_types/register.csv` + `fishing_types/fishing_types.csv` |
| 5 | `cerco_filter.filter_cerco` | `fishing_types/register.csv` | `register.csv` (final) |

Recuentos de referencia de la última corrida: 1 756 → 1 286 → 199 → 51 → 51 → **28**.

### 1. Limpieza — `cleaning/`

`clean_register.py` renombra todas las columnas a inglés (`Correlativo`→`id`,
`Nº RPA`→`RPA`, `Nº Matrícula`→`registration_number`, …), pasa `registration_date`
a ISO 8601, descarta columnas no usadas (`Puerto`, `Venc. Matríc`, `Tipo`, `Rut
Armador`, `Nombre Armador`, `Oficina`) y deduplica conservando, por `(Nº
Matrícula, Puerto)`, la inscripción más reciente. La dedup usa `Puerto` **antes**
de descartarlo (la matrícula sola se reutiliza entre puertos).

```bash
uv run python -m processing.registry.cleaning.clean_register
```

### 2. Filtro por categoría — `filter/`

`filter_register.py` conserva solo `category = LANCHA`, la clase de tamaño de la
flota artesanal relevante.

```bash
uv run python -m processing.registry.filter.filter_register
```

### 3. Emparejamiento IFOP — `ifop_matching/`

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

### 4. Arte de pesca y señal — `fishing_types/`

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

### 5. Filtro final — `cerco_filter/`

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
