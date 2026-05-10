# SST Atacama — Descarga reproducible con Docker

## Qué hace este proyecto

Este proyecto descarga datos diarios del servicio Copernicus Marine para la franja costera de Atacama (latitud -29° a -25°, longitud -72° a -70°) entre 2017 y 2022, los regrilla a una grilla común de 1/24° y los guarda como NetCDF y CSV en la carpeta `data/`. Capas disponibles:

- **SST** — Sea Surface Temperature (°C, diario, ~5 km nativo).
- **CHL** — Chlorophyll-a (mg/m³, diario, 4 km nativo).
- **PHY** — Mixed Layer Depth, salinidad superficial y temperatura potencial a ~400 m (diario, 1/12°).
- **BGC** — Oxígeno disuelto mínimo 0–200 m (proxy del techo de la OMZ), zooplancton, fitoplancton y producción primaria neta (diario, 0.25°).
- **SLA** — Anomalía del nivel del mar, topografía dinámica absoluta y velocidades geostróficas u/v (diario, 0.25°).
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

La primera ejecución construye la imagen (puede tardar unos minutos). Al finalizar, los archivos quedan en `./data/`:

- `sst_atacama_2017_2022.nc` / `.csv` — SST con columnas `time, latitude, longitude, analysed_sst_celsius`.
- `chl_atacama_2017_2022.nc` / `.csv` — clorofila con columnas `time, latitude, longitude, chl_mg_m3`.
- `phy_atacama_2017_2022.nc` / `.csv` — columnas `mlotst, so_0m, thetao_400m`.
- `bgc_atacama_2017_2022.nc` / `.csv` — columnas `o2_min_0_200m, zooc, phyc, nppv`.
- `sla_atacama_2017_2022.nc` / `.csv` — columnas `sla, adt, ugos, vgos`.
- `wind_atacama_2017_2022.nc` / `.csv` — columnas `eastward_wind, northward_wind`.

Cada script imprime un resumen con cantidad de filas, rango temporal y estadísticas básicas en las unidades correspondientes.

## Enriquecer lances con todas las capas

Una vez descargados al menos los NetCDF de SST y CHL (las demás capas son opcionales) y filtrado `data/ships_filtered.csv` (con las columnas `LATITUD_DD`, `LONGITUD_DD`, `FECHA_HORA_ZARPE_UTC`), puedes cruzar las fuentes:

```bash
docker compose run --rm enrich_ships
```

El script genera `data/ships_enriched.csv` (mismo separador `;`) preservando todas las columnas originales y agregando:

- `LAT_GRILLA`, `LON_GRILLA` — coordenadas de la celda de grilla más cercana con datos.
- `DISTANCIA_KM_GRILLA` — distancia aproximada lance↔celda (km).
- Una columna por cada variable presente en los NetCDFs descargados:
  - SST: `analysed_sst_celsius` (°C).
  - CHL: `chl_mg_m3` (mg/m³).
  - PHY: `mlotst` (m), `so_0m` (PSU), `thetao_400m` (°C).
  - BGC: `o2_min_0_200m` (mmol/m³), `zooc`, `phyc` (mmol/m³), `nppv` (mg C/m³/día).
  - SLA: `sla`, `adt` (m), `ugos`, `vgos` (m/s).
  - WIND: `eastward_wind`, `northward_wind` (m/s).

Para cada lance se busca, dentro de la grilla 1/24°, la celda no-nula más cercana donde estén presentes simultáneamente SST y CHL ese día (UTC). El resto de variables se muestrean en esa misma celda sin requisito adicional de no-nulidad: si la celda elegida cae sobre tierra para una variable (típico de SLA y MLD costeros) o no está cubierta por el producto ese día, esa columna queda NaN para esa fila.

Lances fuera del bounding box, sin coordenadas, sin fecha UTC válida o en días totalmente cubiertos por nubes/tierra quedan con NaN en todas las columnas nuevas (no abortan). Si alguno de los NetCDF opcionales (PHY, BGC, SLA, WIND) no está presente en `data/`, el script imprime un aviso por stderr y las columnas correspondientes quedan NaN — útil para flujos parciales (p. ej. sólo SST + CHL). El resumen final imprime cuántas filas cayeron en cada categoría y qué variables agregó.

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

Luego edita la constante `DATASET_ID` al inicio de `downloads/download_sst.py`.

**Error: dataset CHL no encontrado o renombrado.**
El script usa el dataset `cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D` (dentro del producto `OCEANCOLOUR_GLO_BGC_L4_MY_009_104`). Los nombres de dataset cambiaron en la migración de plataforma de Copernicus en 2024 y podrían volver a cambiar. Si esto pasa:

```bash
docker compose run --rm download_chl python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['OCEANCOLOUR_GLO_BGC_L4_MY_009_104'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-oc_glo_bgc-plankton[a-z0-9_-]+', out)))))"
```

Esto imprime todos los datasets de plancton dentro del producto. Elige el que termine en `_P1D` (diario) y contenga `gapfree-multi-4km` (gap-filled, 4 km, multi-sensor). Luego edita la constante `DATASET_ID` al inicio de `downloads/download_chl.py`.

**Error: dataset PHY (físico) no encontrado o renombrado.**
El script usa `cmems_mod_glo_phy_my_0.083deg_P1D-m` dentro del producto `GLOBAL_MULTIYEAR_PHY_001_030` (Mercator GLORYS12, diario, 1/12°). Para descubrir el ID actual:

```bash
docker compose run --rm download_phy python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['GLOBAL_MULTIYEAR_PHY_001_030'])); print('\n'.join(sorted(set(re.findall(r'cmems_mod_glo_phy[a-z0-9_.-]+', out)))))"
```

Elige el que termine en `_P1D-m` (medias diarias). Luego edita `DATASET_ID` en `downloads/download_phy.py`.

**Error: dataset BGC (biogeoquímico) no encontrado o renombrado.**
El script usa `cmems_mod_glo_bgc_my_0.25deg_P1D-m` dentro del producto `GLOBAL_MULTIYEAR_BGC_001_029`. Para descubrir el ID actual:

```bash
docker compose run --rm download_bgc python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['GLOBAL_MULTIYEAR_BGC_001_029'])); print('\n'.join(sorted(set(re.findall(r'cmems_mod_glo_bgc[a-z0-9_.-]+', out)))))"
```

Elige el que termine en `_P1D-m`. Luego edita `DATASET_ID` en `downloads/download_bgc.py`.

**Error: dataset SLA (altimetría) no encontrado o renombrado.**
El script usa `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.25deg_P1D` dentro del producto `SEALEVEL_GLO_PHY_L4_MY_008_047`. Para descubrir el ID actual:

```bash
docker compose run --rm download_sla python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['SEALEVEL_GLO_PHY_L4_MY_008_047'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-sl_glo_phy[a-z0-9_.-]+', out)))))"
```

Elige el que contenga `allsat-l4-duacs` y termine en `_P1D`. Luego edita `DATASET_ID` en `downloads/download_sla.py`.

**Error: dataset WIND (vientos) no encontrado o renombrado.**
El script usa `cmems_obs-wind_glo_phy_my_l4_0.125deg_PT1H` dentro del producto `WIND_GLO_PHY_L4_MY_012_006`. Para descubrir el ID actual:

```bash
docker compose run --rm download_wind python -c "import copernicusmarine, re; out = str(copernicusmarine.describe(contains=['WIND_GLO_PHY_L4_MY_012_006'])); print('\n'.join(sorted(set(re.findall(r'cmems_obs-wind_glo_phy[a-z0-9_.-]+', out)))))"
```

Si Copernicus publica un dataset ya pre-agregado a paso diario (`_P1D` en lugar de `_PT1H`), conviene usarlo: ahorra ~24× espacio en disco. Si lo eliges, edita `DATASET_ID` en `downloads/download_wind.py` y borra/comenta la línea `ds.resample(time="1D").mean()` en `regrid_and_export`.

**Saltos de línea en Windows.**
Si editas `.env` o `download_sst.py` con un editor que guarda en formato CRLF, normalmente no hay problema porque Python tolera ambos formatos. Si aparece algún error raro, configura tu editor (VS Code, Notepad++) para guardar en LF.

**Permiso denegado al escribir en `data/`.**
En Linux puede aparecer si el usuario del contenedor no coincide con el del host. En macOS y Windows con Docker Desktop esto no debería ocurrir; si pasa, ejecuta `chmod -R u+w data/`.

## Estructura del proyecto

```
sst_atacama/
├── Dockerfile             # imagen basada en python:3.11-slim
├── docker-compose.yml     # servicios download_{sst,chl,phy,bgc,sla,wind}, download_all,
│                          # filter_ships, enrich_ships, jupyter
├── requirements.txt       # dependencias Python
├── utils/                 # paquete con helpers compartidos
│   ├── __init__.py
│   └── cmems_common.py    # credenciales + grilla destino unificada + resumen
├── downloads/             # paquete con los descargadores Copernicus Marine
│   ├── __init__.py
│   ├── download_sst.py    # SST (METOFFICE-GLO-SST-L4-REP-OBS-SST)
│   ├── download_chl.py    # CHL (OCEANCOLOUR_GLO_BGC_L4_MY_009_104)
│   ├── download_phy.py    # MLD/SSS/thetao_400m (GLOBAL_MULTIYEAR_PHY_001_030)
│   ├── download_bgc.py    # O₂ min, zooc, phyc, nppv (GLOBAL_MULTIYEAR_BGC_001_029)
│   ├── download_sla.py    # sla, adt, ugos, vgos (SEALEVEL_GLO_PHY_L4_MY_008_047)
│   └── download_wind.py   # vientos a 10 m (WIND_GLO_PHY_L4_MY_012_006)
├── filters/               # paquete con filtros sobre CSVs locales
│   ├── __init__.py
│   └── filter_ships.py    # filtra data/ships.csv (flota Artesanal, Región de Atacama)
├── enrich/                # paquete con cruces espaciotemporales
│   ├── __init__.py
│   └── enrich_ships.py    # cruza ships_filtered.csv con todos los NetCDF presentes
├── .env.example           # plantilla de credenciales (sin valores)
├── .env                   # credenciales reales (NO se versiona)
├── .gitignore
├── README.md
└── data/                  # archivos generados (montado como volumen)
```

> Los `.py` se ejecutan con `python -m <paquete>.<modulo>` desde `/app` (ya
> configurado en `docker-compose.yml`); así el `from utils.cmems_common import …`
> de los descargadores resuelve sin trucos de `sys.path`.
