# Imagen base ligera con Python 3.11
FROM python:3.11-slim

# Dependencias del sistema requeridas por netCDF4 / scipy en linux/arm64 y linux/amd64
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libnetcdf-dev \
        libhdf5-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias de Python primero para aprovechar la cache de Docker
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar los paquetes: utils (helpers compartidos), downloads (SST/CHL),
# filters (filtros sobre CSVs locales) y enrich (cruce de lances con SST/CHL).
# Cada uno es un paquete Python con __init__.py, así que los scripts se
# invocan con `python -m <paquete>.<modulo>` desde el WORKDIR /app
# (ver docker-compose.yml).
COPY utils/ /app/utils/
COPY downloads/ /app/downloads/
COPY filters/ /app/filters/
COPY enrich/ /app/enrich/

# Comando por defecto inocuo; cada servicio del docker-compose define el suyo
CMD ["python", "--version"]
