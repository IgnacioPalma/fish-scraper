# Ejecución en la nube (GitHub Actions + Cloudflare R2)

El pipeline histórico corre en GitHub Actions y deja el corpus crudo **y** los
productos finales en un bucket de Cloudflare R2. Nada necesita correr en una
máquina local: los scrapers lentos corren en la nube (rara vez, porque los
crudos históricos son estáticos) y el procesamiento corre sobre ese corpus
cacheado.

## Idea general

Hay **dos workflows** con roles separados:

| Workflow | Disparo | Qué hace |
| --- | --- | --- |
| [`refresh-raw`](../.github/workflows/refresh-raw.yml) | manual (`workflow_dispatch`) | Corre los scrapers/descargadores IFOP, registro y Copernicus en la nube y cachea su parte del **corpus crudo** en R2. Se corre rara vez. |
| [`vms-refresh`](../.github/workflows/vms-refresh.yml) | manual; **se re-despacha sola** | Descarga los reportes VMS diarios a R2 por tandas y se re-dispara hasta terminar (ver abajo). |
| [`pipeline`](../.github/workflows/pipeline.yml) | manual + cron semanal | Baja el corpus crudo de R2 y corre `run_all --skip-scrape --skip-download` (solo cómputo). Publica el **dataset de modelado**. |

La separación existe por el tope de 6 h por job de GitHub Actions: el scraper
IFOP tarda ~2–2.5 h, así que se aísla en `refresh-raw` (con checkpoint, ver
abajo), y la descarga VMS —la más larga— vive en `vms-refresh` con bucle de
re-despacho; ninguna se repite en cada corrida de `pipeline`.

## Distribución en R2 (`s3://<bucket>/`)

El "corpus crudo" es exactamente lo que reutiliza `--skip-scrape --skip-download`:

```
raw/
  ifop/raw/                    ← scraper IFOP (viajes_observadores.csv + checkpoint)
  registry/raw/                ← scraper registro nacional (by_region/)
  registry/fishing_types/      ← scraper RPA de artes (raw_scrape.csv)
  locations/raw_daily/         ← descarga VMS diaria (~1025 CSV, 1.4 GB)
  copernicus/                  ← grillas Copernicus (.nc + .csv, ~1 GB)
output/
  zarpes_atacama_haul_env.csv  ← producto final (+ diccionario)
```

El mapeo componente lógico ↔ prefijo R2 ↔ carpeta local vive en un solo lugar:
[`scripts/r2_common.sh`](../scripts/r2_common.sh) (`r2_paths`).

## `refresh-raw`: jobs

Cada job baja su porción de `raw/` desde R2 **antes** de scrapear (para que el
skip-if-exists funcione) y la vuelve a subir al terminar. Escriben claves R2
disjuntas, así que corren en paralelo salvo la dependencia indicada.

1. **`ifop`** — scrapea el SIEM (~2.5 h, reanudable por checkpoint) → `raw/ifop/`.
2. **`copernicus`** *(matriz sst/chl/phy/bgc, paralelo)* — descarga cada grilla → `raw/copernicus/`.
3. **`registry`** *(depende de `ifop`)* — el scrape por RPA necesita `vessels.csv`
   de IFOP: baja el crudo de IFOP, corre `ifop.run_pipeline --skip-scrape` para
   derivar `vessels.csv`, luego `registry.run_pipeline` (nacional + fishing_types)
   → `raw/registry/`.

La descarga VMS **no** está en `refresh-raw`: corre en `vms-refresh` (abajo).

## `vms-refresh`: descarga VMS en bucle

El corpus VMS (~1000+ días, 1.4 GB) puede no caber en una sola corrida bajo el
tope de 6 h. `vms-refresh` lo resuelve sin intervención humana:

- **Tandas con flush a R2**: descarga en tandas de `CHUNK_MIN` (15 min) y sube a
  R2 tras **cada** tanda, así un corte pierde a lo sumo una tanda (no la corrida
  entera). El descargador acepta `--max-minutes N`: al agotar el presupuesto sale
  con código `75` ("queda trabajo") o `0` ("todo listo").
- **Marcador central de progreso**: `download_locations` escribe
  `raw_daily/_vms_progress.json` (`{total, downloaded, remaining, last_date,
  complete}`) y lo sube a R2 con los días. Es la fuente única para saber "N/total"
  (p. ej. 559/2131) sin contar archivos. En el log de cada tanda también aparece
  el contador `[559/2131] 2023-05-12 …`.
- **Caché de fechas faltantes** (`raw_daily/_vms_missing.txt`): un día sin dato en
  el servidor devuelve 404 y NO deja archivo; en el formato antiguo confirmarlo
  cuesta ~90 s (barrido `SS=00..59`). Sin caché, cada tanda re-intentaba las mismas
  fechas faltantes y no avanzaba (bucle infinito). Ahora se registran y se saltan
  al instante en las tandas siguientes. Un 404 es definitivo (los errores
  transitorios abortan, no se cachean); el día de hoy nunca se cachea.
- **Cursor de reanudación** (`raw_daily/_vms_cursor.json`): guarda la frontera
  contigua de lo ya resuelto (descargado o faltante-cacheado), así cada tanda
  arranca en la frontera en vez de re-escanear desde el inicio (evita ~2000 líneas
  de log por tanda y hace la reanudación instantánea). La frontera solo avanza por
  fechas resueltas y contiguas —nunca salta una pendiente (p. ej. hoy sin
  publicar)—, y si cambia el rango global (`START`/`END`) el cursor se invalida y
  se re-escanea todo (seguro).
- **Auto-continuación**: si el job agota su presupuesto total (`TOTAL_BUDGET_MIN`,
  < `timeout-minutes`) sin terminar, se re-despacha solo con
  `gh workflow run vms-refresh.yml` (permitido con el `GITHUB_TOKEN` por defecto
  para `workflow_dispatch`). Para si el descargador recorrió todas las fechas, o
  al llegar a `MAX_ATTEMPTS` re-despachos (red de seguridad).

Consultar el progreso en cualquier momento:

```bash
scripts/r2_pull.sh vms   # trae _vms_progress.json (entre otros)
cat data/processing/locations/raw_daily/_vms_progress.json
```

### Reanudación (checkpointing)

- **IFOP** escribe un checkpoint incremental por observador
  (`viajes_observadores.partial.csv` / `scrape_siem_log.partial.csv`); si el job
  se corta, la próxima corrida salta los observadores ya hechos. Al completarse,
  consolida los CSV finales y borra los parciales.
- **VMS** salta los días ya descargados y persiste su progreso por tandas (ver
  `vms-refresh` arriba); **registro nacional** cachea por región;
  **fishing_types** escribe filas incrementalmente.
- **Copernicus** salta la descarga si el `.nc` y el `.csv` ya existen (usar
  `--force` para rebajar).
- Además, cada job baja su porción de R2 antes de correr, así que una re-corrida
  reanuda desde lo que ya está en R2 (segunda capa de seguridad).

## `pipeline`: procesamiento

Baja `raw/` completo de R2, corre `run_all --skip-scrape --skip-download`
(sin navegador, acotado a decenas de minutos), sube `data/output/` a R2 y publica
el dataset como *artifact* del workflow.

## Secrets (GitHub → Settings → Secrets and variables → Actions)

- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
  (tokens R2 en el panel de Cloudflare → R2 → *Manage API Tokens*).
- `COPERNICUS_USERNAME`, `COPERNICUS_PASSWORD` (solo el job `copernicus`).

Los mismos nombres están documentados en [`.env.example`](../.env.example) para
uso local.

## Uso local de R2 (opcional, para depurar)

Requiere `aws-cli` y las variables R2 en `.env`. Los scripts leen `.env`
automáticamente:

```bash
scripts/r2_pull.sh                 # baja el corpus crudo completo (raw)
scripts/r2_pull.sh copernicus      # solo las grillas
scripts/r2_push.sh output          # sube los productos finales
scripts/r2_push.sh raw output      # sube crudo + productos
```

Componentes válidos: `ifop | registry | vms | copernicus | raw | output`.

## Primer arranque

1. Crear el bucket R2 y un token de API; cargar los secrets en GitHub.
2. Disparar `refresh-raw` a mano (IFOP + registro + Copernicus; primera corrida
   ~3 h de reloj; siguientes: casi instantáneas por skip-if-exists).
3. Disparar `vms-refresh` a mano (se re-despacha sola hasta bajar todo el VMS).
4. Disparar `pipeline` (o esperar el cron), una vez que `refresh-raw` y
   `vms-refresh` completaron: produce y publica `zarpes_atacama_haul_env.csv` en
   R2 y como artifact.
