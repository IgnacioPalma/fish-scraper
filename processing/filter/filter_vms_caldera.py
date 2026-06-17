"""
Filtra el archivo consolidado de posiciones VMS (flota artesanal) a los
registros dentro de RADIUS_KM kilómetros del puerto de Caldera.

El resultado se escribe a data/filter/vms_near_caldera.csv con las columnas
originales del VMS más LOCATION_DATETIME (ISO), DIST_KM y SPEED_KT (números).

Entrada: data/locations/locations_flota_artesanal_2023_2024.csv
         (si no existe, busca la versión solo-2023)
Salida:  data/filter/vms_near_caldera.csv
"""

import json
import math
import os
import sys
from pathlib import Path

import pandas as pd


DATA_DIR   = Path(__file__).resolve().parent.parent.parent / "data"
PORTS_JSON = Path(__file__).resolve().parent.parent / "bitacora" / "puertos_atacama.json"
OUTPUT_DIR = DATA_DIR / "filter"
OUTPUT_CSV = OUTPUT_DIR / "vms_near_caldera.csv"

VMS_CANDIDATES = [
    DATA_DIR / "locations" / "locations_flota_artesanal_2023_2024.csv",
    DATA_DIR / "locations" / "locations_flota_artesanal_2023.csv",
]

RADIUS_KM = 10.0

VMS_COL_NAME  = "Name"
VMS_COL_RC    = "Radio Call Sign (RC)"
VMS_COL_DATE  = "Location date"
VMS_COL_LAT   = "Latitude"
VMS_COL_LON   = "Longitude"
VMS_COL_HEAD  = "Heading"
VMS_COL_SPEED = "Speed (kt)"
VMS_DATE_FMT  = "%d/%m/%Y %H:%M:%S"

REQUIRED_COLS = [VMS_COL_NAME, VMS_COL_RC, VMS_COL_DATE,
                 VMS_COL_LAT, VMS_COL_LON, VMS_COL_HEAD, VMS_COL_SPEED]


def _resolver_vms() -> Path:
    for p in VMS_CANDIDATES:
        if p.exists():
            return p
    print(
        "ERROR: no se encontró el archivo consolidado de posiciones VMS.\n"
        "       Ejecutá primero:\n"
        "         uv run python -m processing.locations.consolidate_locations",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    vms_path = _resolver_vms()

    if not PORTS_JSON.exists():
        print(f"ERROR: no se encontró {PORTS_JSON}.", file=sys.stderr)
        sys.exit(2)

    with PORTS_JSON.open(encoding="utf-8") as f:
        puertos = json.load(f)

    caldera = next((p for p in puertos if p["nombre"] == "Caldera"), None)
    if caldera is None:
        print("ERROR: Caldera no encontrada en puertos_atacama.json.", file=sys.stderr)
        sys.exit(2)

    caldera_lat = caldera["latitud"]
    caldera_lon = caldera["longitud"]
    cos_lat = math.cos(math.radians(caldera_lat))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    chunks_filtrados = []
    total_leidas = 0
    cols_validadas = False

    for chunk in pd.read_csv(
        vms_path,
        sep=";",
        dtype=str,
        encoding="utf-8-sig",
        chunksize=200_000,
    ):
        total_leidas += len(chunk)

        if not cols_validadas:
            faltantes = [c for c in REQUIRED_COLS if c not in chunk.columns]
            if faltantes:
                print(
                    f"ERROR: columnas faltantes en el VMS: {faltantes}.",
                    file=sys.stderr,
                )
                sys.exit(2)
            cols_validadas = True

        # Coordenadas: remover símbolo ° presente en registros 2024
        lat = pd.to_numeric(
            chunk[VMS_COL_LAT].str.replace("°", "", regex=False),
            errors="coerce",
        )
        lon = pd.to_numeric(
            chunk[VMS_COL_LON].str.replace("°", "", regex=False),
            errors="coerce",
        )

        # Velocidad: remover sufijo " kt"
        speed = pd.to_numeric(
            chunk[VMS_COL_SPEED].str.replace(" kt", "", regex=False),
            errors="coerce",
        )

        mask_validas = lat.notna() & lon.notna()
        if not mask_validas.any():
            continue

        # Distancia coseno-ajustada a Caldera (igual que _nearest_port en clean_bitacora)
        dlat = lat[mask_validas] - caldera_lat
        dlon = (lon[mask_validas] - caldera_lon) * cos_lat
        dist = (dlat ** 2 + dlon ** 2).pow(0.5) * 111.32

        mask_cerca = dist <= RADIUS_KM
        if not mask_cerca.any():
            continue

        idx_cerca = dist[mask_cerca].index
        sub = chunk.loc[idx_cerca].copy()
        sub["LOCATION_DATETIME"] = pd.to_datetime(
            sub[VMS_COL_DATE], format=VMS_DATE_FMT, errors="coerce"
        ).dt.strftime("%Y-%m-%d %H:%M:%S")
        sub["DIST_KM"]   = dist[mask_cerca].round(3).values
        sub["SPEED_KT"]  = speed.loc[idx_cerca].round(2).values

        chunks_filtrados.append(sub)

    if not chunks_filtrados:
        print(
            "ERROR: ningún registro VMS quedó dentro del radio de Caldera.\n"
            f"       Radio usado: {RADIUS_KM} km.",
            file=sys.stderr,
        )
        sys.exit(1)

    df_out = pd.concat(chunks_filtrados, ignore_index=True)

    tmp = OUTPUT_CSV.with_suffix(".tmp")
    df_out.to_csv(tmp, sep=";", index=False, encoding="utf-8")
    os.replace(tmp, OUTPUT_CSV)

    print(
        f"Archivo VMS utilizado:          {vms_path}\n"
        f"Filas VMS leídas:               {total_leidas:,}\n"
        f"Filas cerca de Caldera:         {len(df_out):,}  (radio {RADIUS_KM} km)\n"
        f"Nombres VMS únicos:             {df_out[VMS_COL_NAME].nunique():,}\n"
        f"Archivo escrito:                {OUTPUT_CSV}"
    )


if __name__ == "__main__":
    main()
