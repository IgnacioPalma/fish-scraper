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

# Copiar los scripts de descarga y el módulo común
COPY cmems_common.py download_sst.py download_chl.py /app/

# Comando por defecto inocuo; cada servicio del docker-compose define el suyo
CMD ["python", "--version"]
