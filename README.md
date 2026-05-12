# SST Atacama — Descarga reproducible con Docker

## Qué hace este proyecto

Este proyecto descarga datos diarios del servicio Copernicus Marine para la franja costera de Atacama (latitud -29° a -25°, longitud -72° a -70°), los regrilla a una grilla común de 1/24° y los guarda como NetCDF y CSV en la carpeta `data/`. El **rango temporal** que descargan TODOS los servicios se define una sola vez en [processing/utils/date_ranges.py](processing/utils/date_ranges.py) (`START_DATE` / `END_DATE`); cada descargador clipa al subconjunto disponible en su producto. Capas disponibles:

- **SST** — Sea Surface Temperature (°C, diario, ~5 km nativo).
- **CHL** — Chlorophyll-a (mg/m³, diario, 4 km nativo).
- **PHY** — Mixed Layer Depth, salinidad superficial y temperatura potencial a ~400 m (diario, 1/12°).
- **BGC** — Oxígeno disuelto mínimo 0–200 m (proxy del techo de la OMZ) y producción primaria neta (diario, 0.25°). El reanálisis BGC global no expone biomasa de plancton (`phyc`/`zooc`); quedan fuera del alcance de este flujo.
- **SLA** — Anomalía del nivel del mar, topografía dinámica absoluta y velocidades geostróficas u/v (diario, 0.125°).
- **WIND** — Componentes zonal y meridional del viento a 10 m (diario tras agregación, 0.125°).

Todas las capas terminan sobre la misma grilla 1/24° (≈4 km), de modo que un cruce SST↔CHL↔PHY↔BGC↔SLA↔WIND es un `pd.merge(..., on=["time", "latitude", "longitude"])` directo, sin regrillado posterior. También provee un servidor Jupyter para análisis posterior. Todo corre dentro de Docker, así que el entorno es idéntico en macOS y Windows.

## Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y en ejecución (macOS o Windows).
- Una cuenta gratuita en [Copernicus Marine](https://data.marine.copernicus.eu/register).
- ~3–5 GB de espacio libre en disco si descargas las seis capas (SST, CHL, PHY, BGC, SLA, WIND); ~1 GB si sólo bajas SST y CHL.

## Configuración inicial

1. Copia el archivo de ejemplo de credenciales:
   - **macOS / Linux:** `cp .env.example .env`
   - **Windows (PowerShell):** `copy .env.example .env`
2. Abre `.env` con tu editor y completa tus credenciales:
   ```
   COPERNICUS_USERNAME=tu_usuario
   COPERNICUS_PASSWORD=tu_contraseña
   ```
   El archivo `.env` está en `.gitignore`, no se subirá al repositorio.

## Descargar los datos

Desde la carpeta del proyecto (`sst_atacama/`) tienes un servicio por capa más uno de conveniencia:

```bash
# Capas individuales
docker compose run --rm download_sst    # Sea Surface Temperature
docker compose run --rm download_chl    # Chlorophyll-a
docker compose run --rm download_phy    # MLD, salinidad superficial, temp 400 m
docker compose run --rm download_bgc    # O₂ min 0–200 m, zooplancton, fitoplancton, NPP
docker compose run --rm download_sla    # SLA, ADT, ugos, vgos (altimetría)
docker compose run --rm download_wind   # vientos a 10 m (agregados a media diaria)

# Las seis en secuencia (corta a la primera falla)
docker compose run --rm download_all
```

La primera ejecución construye la imagen (puede tardar unos minutos). Al finalizar, los archivos quedan en `./data/`, con un sufijo de año derivado del rango efectivo descargado (intersección de `START_DATE`/`END_DATE` con la disponibilidad del producto):

- `sst_atacama_<rango>.nc` / `.csv` — SST con columnas `time, latitude, longitude, analysed_sst_celsius`.
- `chl_atacama_<rango>.nc` / `.csv` — clorofila con columnas `time, latitude, longitude, chl_mg_m3`.
- `phy_atacama_<rango>.nc` / `.csv` — columnas `mlotst, so_0m, thetao_400m`.
- `bgc_atacama_<rango>.nc` / `.csv` — columnas `o2_min_0_200m, nppv`.
- `sla_atacama_<rango>.nc` / `.csv` — columnas `sla, adt, ugos, vgos`.
- `wind_atacama_<rango>.nc` / `.csv` — columnas `eastward_wind, northward_wind`.

Donde `<rango>` es `2023` para un único año o `2017_2022` si abarca varios. Cada script imprime el rango global solicitado, la disponibilidad del producto y el rango efectivo (intersección) antes de descargar. Si la intersección es vacía (p. ej. el rango global está fuera de la cobertura del reanálisis multi-año), el script lo informa y sale sin descargar.

> **Sobre los productos multi-year:** los seis productos Copernicus que usamos hoy se extienden más allá de su tramo "reanálisis puro" mediante datasets `_myint_` (interim) bajo el mismo product ID — el catálogo de hoy llega a 2025–2026. Las constantes `PRODUCT_START_DATE` / `PRODUCT_END_DATE` en cada `processing/copernicus/download_*.py` declaran el rango disponible y se intersectan con el rango global. Si extendés `END_DATE` y un descargador específico devuelve un error de cobertura temporal, probablemente el `DATASET_ID` `_my_` quedó corto y hay que cambiarlo al `_myint_` correspondiente (ver "Solución de problemas" para los one-liners de descubrimiento).

## Descargar reportes diarios VMS de Sernapesca

Sernapesca publica un CSV por día con las posiciones reportadas por el VMS de la flota artesanal chilena (código de flota 31). Las columnas son las del reporte básico: nombre, indicativo de llamada, fecha/hora, latitud, longitud, rumbo y velocidad. El downloader recorre las fechas del rango global (intersección con la disponibilidad de Sernapesca, que empieza el 3 de marzo de 2019) y guarda un archivo por día en `data/locations/` con el nombre `flota_artesanal_YYYY-MM-DD.csv`.

```bash
docker compose run --rm download_locations
```

El script es idempotente: si una fecha ya está descargada se salta, así que se puede interrumpir y volver a correr sin re-descargar. No necesita credenciales (el sitio de Sernapesca es público).

Detrás de escena conviven dos patrones de URL por una migración de CMS (Drupal → WordPress) hacia mediados de 2022. El script rutea cada fecha **estrictamente** a un formato u otro según el corte definido en [processing/utils/locations_common.py](processing/utils/locations_common.py) (`OLD_FORMAT_END`) — no hay fallback cruzado:

- Formato antiguo (Drupal, hasta `OLD_FORMAT_END` inclusive): `https://www.sernapesca.cl/sites/default/files/report-YYYY-MM-DD_11_45_SS-sernapesca-admin.csv`. La hora:minuto es siempre `11:45`, pero los segundos varían entre 00 y 59 — el script itera hasta dar con el archivo.
- Formato nuevo (WordPress, desde el día siguiente a `OLD_FORMAT_END`): `https://www.sernapesca.cl/app/uploads/YYYY/MM/report_31_YYYYMMDD_flota_artesanal.csv`. Para fechas recientes la subida es del mismo mes; los archivos antiguos de la era WordPress fueron resubidos en bloque a `/BACKFILL_YEAR_MONTH/`, así que el script intenta ambos dentro de este mismo formato.

El rango efectivo es la intersección del rango global ([processing/utils/date_ranges.py](processing/utils/date_ranges.py)) con la disponibilidad de Sernapesca (`EARLIEST_AVAILABLE` en `locations_common.py`). Para mover/recortar el rango temporal del proyecto editá `date_ranges.py`; para ajustar el corte de formato u otros detalles de URLs editá `locations_common.py`. En ambos casos reconstruí la imagen (ver `--build` en *Solución de problemas*).

La descarga es secuencial y educada (0,5 s entre solicitudes). Cubrir el rango completo puede tardar varias horas la primera vez, sobre todo por el formato antiguo que requiere probar múltiples timestamps por fecha. Las fechas sin archivo en el servidor (fines de semana sin publicación, caídas puntuales) se reportan como "faltantes" en el resumen final sin abortar la corrida.

## Limpiar el registro de embarcaciones

El archivo `data/register.csv` es el registro histórico de embarcaciones de Atacama. Una misma nave aparece varias veces cuando cambia de armador (cada inscripción agrega una fila con un nuevo `Nº RPA`, pero la `Nº Matrícula` del puerto se mantiene). Para alinear el registro con los reportes diarios de VMS de Sernapesca conviene quedarse con la inscripción más reciente por embarcación y, por ahora, restringir el análisis a la categoría `LANCHA`.

```bash
docker compose run --rm clean_register
```

El script lee `data/register.csv`, filtra a `Categoría = LANCHA`, parsea `Fecha Inscripción` (`DD-MM-YYYY`) y conserva, para cada par `(Nº Matrícula, Puerto)`, la fila con la fecha más reciente. El resultado se escribe en `data/register_clean.csv` (mismo separador `;`, mismas columnas) e imprime un resumen con cuántas filas se descartaron por categoría, fecha inválida y duplicado.

## Filtrar desembarques (landings)

`data/desembarques.csv` es la tabla mensual de desembarques de Sernapesca (~16 MB, separador `;`, codificada en latin-1). El script filtra a la combinación que usamos hoy en el análisis bayesiano:

- `ano` ∈ años del rango global ([processing/utils/date_ranges.py](processing/utils/date_ranges.py))
- `region == "Atacama"`
- `tipo_agente == "Artesanal"`
- `especie == "Jurel"`

```bash
docker compose run --rm filter_landings
```

El resultado se escribe en `data/landings/landings_jurel_atacama_artesanal_<rango>.csv` (mismo separador `;`, mismas columnas que la fuente, reescrito en UTF-8 para evitar problemas de encoding aguas abajo). El sufijo `<rango>` se deriva del año global: `2023` para un único año, `2023_2024` si abarca varios. El script imprime un resumen con filas totales, filas tras el filtro y toneladas totales.

Para apuntar el filtro a otra combinación (otra región, otro arte, otra especie), editá las tres constantes `REGION` / `TIPO_AGENTE` / `ESPECIE` al inicio de [processing/landings/filter_landings.py](processing/landings/filter_landings.py) y reconstruí la imagen (ver `--build` en *Solución de problemas*). El filtro por año siempre viene de `date_ranges.py`.

## Iniciar Jupyter

```bash
docker compose up jupyter
```

Luego abre [http://localhost:8888/](http://localhost:8888/) en tu navegador. La carpeta `/app/data` dentro del contenedor corresponde a `./data/` en tu máquina, así que los archivos NetCDF y CSV están disponibles directamente.

> **Nota de seguridad:** el servidor Jupyter no pide token y solo escucha en `localhost`. Si lo expones a otra red, vuelve a habilitar el token en `docker-compose.yml`.

## Detener los contenedores

```bash
docker compose down
```

## Solución de problemas

**Error: faltan credenciales.**
Verifica que `.env` exista junto a `docker-compose.yml` y que las dos variables tengan valor. Recuerda que el archivo se carga al inicio del contenedor: si lo cambias, vuelve a ejecutar el comando de descarga correspondiente.

**Error: dataset SST no encontrado o renombrado.**
El script usa el dataset `METOFFICE-GLO-SST-L4-REP-OBS-SST` (dentro del producto `SST_GLO_SST_L4_REP_OBSERVATIONS_010_011`). Si Copernicus lo renombra, descubre el ID actual y filtra los IDs de dataset:

```bash
docker compose run --rm download_sst python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['SST_GLO_SST_L4_REP_OBSERVATIONS_010_011'])); print('\n'.join(sorted(set(re.findall(r'METOFFICE[A-Z0-9-]+', out)))))"
```

Luego edita la constante `DATASET_ID` al inicio de `processing/copernicus/download_sst.py`.

**Error: dataset CHL no encontrado o renombrado.**
El script usa el dataset `cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D` (dentro del producto `OCEANCOLOUR_GLO_BGC_L4_MY_009_104`). Los nombres de dataset cambiaron en la migración de plataforma de Copernicus en 2024 y podrían volver a cambiar. Si esto pasa:

```bash
docker compose run --rm download_chl python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['OCEANCOLOUR_GLO_BGC_L4_MY_009_104'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-oc_glo_bgc-plankton[a-z0-9_-]+', out)))))"
```

Esto imprime todos los datasets de plancton dentro del producto. Elige el que termine en `_P1D` (diario) y contenga `gapfree-multi-4km` (gap-filled, 4 km, multi-sensor). Luego edita la constante `DATASET_ID` al inicio de `processing/copernicus/download_chl.py`.

**Error: dataset PHY (físico) no encontrado o renombrado.**
El script usa `cmems_mod_glo_phy_my_0.083deg_P1D-m` dentro del producto `GLOBAL_MULTIYEAR_PHY_001_030` (Mercator GLORYS12, diario, 1/12°). Para descubrir el ID actual:

```bash
docker compose run --rm download_phy python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['GLOBAL_MULTIYEAR_PHY_001_030'])); print('\n'.join(sorted(set(re.findall(r'cmems_mod_glo_phy[A-Za-z0-9_.-]+', out)))))"
```

Elige el que termine en `_P1D-m` (medias diarias). Luego edita `DATASET_ID` en `processing/copernicus/download_phy.py`.

**Error: dataset BGC (biogeoquímico) no encontrado o renombrado.**
El script usa `cmems_mod_glo_bgc_my_0.25deg_P1D-m` dentro del producto `GLOBAL_MULTIYEAR_BGC_001_029`. Es un único dataset diario que expone {chl, no3, nppv, o2, po4, si} — **no incluye `phyc` ni `zooc`**, así que el script sólo extrae `o2` (reducido a `o2_min_0_200m`) y `nppv`. Para descubrir el ID actual:

```bash
docker compose run --rm download_bgc python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['GLOBAL_MULTIYEAR_BGC_001_029'])); print('\n'.join(sorted(set(re.findall(r'cmems_mod_glo_bgc[A-Za-z0-9_.-]+', out)))))"
```

Elige el que termine en `_P1D-m`. Luego edita `DATASET_ID` en `processing/copernicus/download_bgc.py`. Si necesitas otra variable del listado (`chl`, `no3`, `po4`, `si`), agrégala a `VARIABLES` y al dict `OUTPUT_VARIABLES`.

**Error: dataset SLA (altimetría) no encontrado o renombrado.**
El script usa `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1D` dentro del producto `SEALEVEL_GLO_PHY_L4_MY_008_047`. Para descubrir el ID actual:

```bash
docker compose run --rm download_sla python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['SEALEVEL_GLO_PHY_L4_MY_008_047'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-sl_glo_phy[A-Za-z0-9_.-]+', out)))))"
```

Elige el que contenga `allsat-l4-duacs` y termine en `_P1D`. Luego edita `DATASET_ID` en `processing/copernicus/download_sla.py`.

**Error: dataset WIND (vientos) no encontrado o renombrado.**
El script usa `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` dentro del producto `WIND_GLO_PHY_L4_MY_012_006`. Para descubrir el ID actual:

```bash
docker compose run --rm download_wind python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['WIND_GLO_PHY_L4_MY_012_006'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-wind_glo_phy[A-Za-z0-9_.-]+', out)))))"
```

Si Copernicus publica un dataset ya pre-agregado a paso diario (`_P1D` en lugar de `_PT1H`), conviene usarlo: ahorra ~24× espacio en disco. Si lo eliges, edita `DATASET_ID` en `processing/copernicus/download_wind.py` y borra/comenta la línea `ds.resample(time="1D").mean()` en `regrid_and_export`.

**Editaste código bajo `processing/` y los cambios no aparecen.**
Ese paquete se *copia* dentro de la imagen al construirla (ver [Dockerfile](Dockerfile)), no se montan como volumen. Si editás un script en el host y volvés a correr el servicio sin reconstruir, Docker reusa la imagen vieja y nada cambia (típicamente se ve como "el script corrió pero no descargó nada y no hubo logs"). Solución: agregá `--build` al comando, que reconstruye la imagen antes de correr el servicio:

```bash
docker compose run --rm --build download_locations
```

Solo es necesario tras editar código; los cambios en `data/` ya son visibles porque sí es un volumen montado.

**Saltos de línea en Windows.**
Si editas `.env` o `download_sst.py` con un editor que guarda en formato CRLF, normalmente no hay problema porque Python tolera ambos formatos. Si aparece algún error raro, configura tu editor (VS Code, Notepad++) para guardar en LF.

**Permiso denegado al escribir en `data/`.**
En Linux puede aparecer si el usuario del contenedor no coincide con el del host. En macOS y Windows con Docker Desktop esto no debería ocurrir; si pasa, ejecuta `chmod -R u+w data/`.

## Estructura del proyecto

```
sst_atacama/
├── Dockerfile             # imagen basada en python:3.11-slim
├── docker-compose.yml     # servicios download_{sst,chl,phy,bgc,sla,wind,locations},
│                          # download_all, clean_register, filter_landings, jupyter
├── requirements.txt       # dependencias Python
├── processing/            # paquete raíz con los subpaquetes de procesamiento
│   ├── __init__.py
│   ├── utils/             # subpaquete con helpers compartidos
│   │   ├── __init__.py
│   │   ├── cmems_common.py    # credenciales + grilla destino unificada + resumen
│   │   ├── date_ranges.py     # rango temporal global (START_DATE / END_DATE)
│   │   └── locations_common.py# formato y URLs Sernapesca (Drupal/WordPress, fleet, backfill)
│   ├── copernicus/        # subpaquete con los descargadores Copernicus Marine
│   │   ├── __init__.py
│   │   ├── download_sst.py    # SST (METOFFICE-GLO-SST-L4-REP-OBS-SST)
│   │   ├── download_chl.py    # CHL (OCEANCOLOUR_GLO_BGC_L4_MY_009_104)
│   │   ├── download_phy.py    # MLD/SSS/thetao_400m (GLOBAL_MULTIYEAR_PHY_001_030)
│   │   ├── download_bgc.py    # O₂ min, nppv (GLOBAL_MULTIYEAR_BGC_001_029)
│   │   ├── download_sla.py    # sla, adt, ugos, vgos (SEALEVEL_GLO_PHY_L4_MY_008_047)
│   │   └── download_wind.py   # vientos a 10 m (WIND_GLO_PHY_L4_MY_012_006)
│   ├── locations/         # subpaquete con el descargador VMS de Sernapesca
│   │   ├── __init__.py
│   │   └── download_locations.py  # CSV diarios VMS (flota artesanal)
│   ├── register/          # subpaquete con preprocesamiento del registro
│   │   ├── __init__.py
│   │   └── clean_register.py  # data/register.csv → data/register_clean.csv (LANCHA, dedup)
│   └── landings/          # subpaquete con filtros sobre desembarques
│       ├── __init__.py
│       └── filter_landings.py # data/desembarques.csv → data/landings/landings_<filtro>_<rango>.csv
├── .env.example           # plantilla de credenciales (sin valores)
├── .env                   # credenciales reales (NO se versiona)
├── .gitignore
├── README.md
└── data/                  # archivos generados (montado como volumen)
```

> Los `.py` se ejecutan con `python -m processing.<subpaquete>.<modulo>`
> desde `/app` (ya configurado en `docker-compose.yml`); así el
> `from processing.utils.cmems_common import …` de los descargadores
> resuelve sin trucos de `sys.path`.
