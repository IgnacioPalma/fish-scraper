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

# Copiar el paquete `processing/` con sus subpaquetes: utils (helpers
# compartidos), copernicus (descargadores Copernicus Marine), locations
# (descargador VMS Sernapesca) y register (preprocesamiento de registros).
# Cada uno es un paquete Python con __init__.py, así que los scripts se
# invocan con `python -m processing.<subpaquete>.<modulo>` desde el WORKDIR
# /app (ver docker-compose.yml).
COPY processing/ /app/processing/

# Comando por defecto inocuo; cada servicio del docker-compose define el suyo
CMD ["python", "--version"]
