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
| [`refresh-raw`](../.github/workflows/refresh-raw.yml) | manual (`workflow_dispatch`) | Corre scrapers/descargadores en la nube y cachea el **corpus crudo** en R2. Se corre rara vez. |
| [`pipeline`](../.github/workflows/pipeline.yml) | manual + cron semanal | Baja el corpus crudo de R2 y corre `run_all --skip-scrape --skip-download` (solo cómputo). Publica el **dataset de modelado**. |

La separación existe por el tope de 6 h por job de GitHub Actions: el scraper
IFOP tarda ~2–2.5 h, así que se aísla en `refresh-raw` (con checkpoint, ver
abajo) y no se repite en cada corrida de `pipeline`.

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
2. **`vms`** *(paralelo)* — descarga los reportes VMS diarios → `raw/locations/raw_daily/`.
3. **`copernicus`** *(matriz sst/chl/phy/bgc, paralelo)* — descarga cada grilla → `raw/copernicus/`.
4. **`registry`** *(depende de `ifop`)* — el scrape por RPA necesita `vessels.csv`
   de IFOP: baja el crudo de IFOP, corre `ifop.run_pipeline --skip-scrape` para
   derivar `vessels.csv`, luego `registry.run_pipeline` (nacional + fishing_types)
   → `raw/registry/`.

### Reanudación (checkpointing)

- **IFOP** escribe un checkpoint incremental por observador
  (`viajes_observadores.partial.csv` / `scrape_siem_log.partial.csv`); si el job
  se corta, la próxima corrida salta los observadores ya hechos. Al completarse,
  consolida los CSV finales y borra los parciales.
- **VMS** ya salta los días ya descargados; **registro nacional** cachea por
  región; **fishing_types** escribe filas incrementalmente.
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
2. Disparar `refresh-raw` a mano (primera corrida: scrape completo, ~3 h de
   reloj; corridas siguientes: casi instantáneas por skip-if-exists).
3. Disparar `pipeline` (o esperar el cron): produce y publica
   `zarpes_atacama_haul_env.csv` en R2 y como artifact.
