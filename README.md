# SST Atacama — Descarga reproducible con Docker

## Qué hace este proyecto

Este proyecto descarga datos diarios de **Sea Surface Temperature (SST)** y **Chlorophyll-a (CHL)** del servicio Copernicus Marine para la franja costera de Atacama (latitud -29° a -25°, longitud -72° a -70°) entre 2017 y 2022, y los guarda como NetCDF y CSV en la carpeta `data/`. También provee un servidor Jupyter para análisis posterior. Todo corre dentro de Docker, así que el entorno es idéntico en macOS y Windows.

## Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y en ejecución (macOS o Windows).
- Una cuenta gratuita en [Copernicus Marine](https://data.marine.copernicus.eu/register).
- ~1 GB de espacio libre en disco para los archivos descargados (SST y CHL combinados).

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

Desde la carpeta del proyecto (`sst_atacama/`) tienes tres opciones:

```bash
# Solo SST
docker compose run --rm download_sst

# Solo clorofila
docker compose run --rm download_chl

# Ambos en secuencia (SST primero, luego CHL)
docker compose run --rm download_all
```

La primera ejecución construye la imagen (puede tardar unos minutos). Al finalizar, los archivos quedan en `./data/`:

- `sst_atacama_2017_2022.nc` / `.csv` — SST con columnas `time, latitude, longitude, analysed_sst_celsius`.
- `chl_atacama_2017_2022.nc` / `.csv` — clorofila con columnas `time, latitude, longitude, chl_mg_m3`.

Cada script imprime un resumen con cantidad de filas, rango temporal y estadísticas básicas (°C para SST, mg/m³ para CHL).

## Enriquecer lances con SST y CHL

Una vez descargados los NetCDF de SST y CHL y filtrado `data/ships_filtered.csv` (con las columnas `LATITUD_DD`, `LONGITUD_DD`, `FECHA_HORA_ZARPE_UTC`), puedes cruzar ambas fuentes:

```bash
docker compose run --rm enrich_ships
```

El script genera `data/ships_enriched.csv` (mismo separador `;`) preservando todas las columnas originales y agregando cinco:

- `LAT_GRILLA`, `LON_GRILLA` — coordenadas de la celda de grilla más cercana con datos.
- `DISTANCIA_KM_GRILLA` — distancia aproximada lance↔celda (km).
- `analysed_sst_celsius` — SST de esa celda en °C.
- `chl_mg_m3` — clorofila-a de esa celda en mg/m³.

Para cada lance se busca, dentro de la grilla 1/24°, la celda no-nula más cercana donde estén presentes simultáneamente SST y CHL ese día (UTC). Lances fuera del bounding box, sin coordenadas, sin fecha UTC válida o en días totalmente cubiertos por nubes/tierra quedan con NaN en las cinco columnas (no abortan). El resumen final imprime cuántas filas cayeron en cada categoría.

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

**Saltos de línea en Windows.**
Si editas `.env` o `download_sst.py` con un editor que guarda en formato CRLF, normalmente no hay problema porque Python tolera ambos formatos. Si aparece algún error raro, configura tu editor (VS Code, Notepad++) para guardar en LF.

**Permiso denegado al escribir en `data/`.**
En Linux puede aparecer si el usuario del contenedor no coincide con el del host. En macOS y Windows con Docker Desktop esto no debería ocurrir; si pasa, ejecuta `chmod -R u+w data/`.

## Estructura del proyecto

```
sst_atacama/
├── Dockerfile             # imagen basada en python:3.11-slim
├── docker-compose.yml     # servicios download_sst, download_chl, download_all, filter_ships, enrich_ships, jupyter
├── requirements.txt       # dependencias Python
├── utils/                 # paquete con helpers compartidos
│   ├── __init__.py
│   └── cmems_common.py    # credenciales + grilla destino unificada + resumen
├── downloads/             # paquete con los descargadores
│   ├── __init__.py
│   ├── download_sst.py    # descarga SST + regrilla + exporta CSV
│   └── download_chl.py    # descarga CHL + regrilla + exporta CSV
├── filters/               # paquete con filtros sobre CSVs locales
│   ├── __init__.py
│   └── filter_ships.py    # filtra data/ships.csv (flota Artesanal, Región de Atacama)
├── enrich/                # paquete con cruces espaciotemporales
│   ├── __init__.py
│   └── enrich_ships.py    # cruza ships_filtered.csv con NetCDF de SST/CHL
├── .env.example           # plantilla de credenciales (sin valores)
├── .env                   # credenciales reales (NO se versiona)
├── .gitignore
├── README.md
└── data/                  # archivos generados (montado como volumen)
```

> Los `.py` se ejecutan con `python -m <paquete>.<modulo>` desde `/app` (ya
> configurado en `docker-compose.yml`); así el `from utils.cmems_common import …`
> de los descargadores resuelve sin trucos de `sys.path`.
