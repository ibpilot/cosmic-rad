#!/usr/bin/env python3
"""Convierte un NetCDF SGPS L2 avg5m de NCEI/NGDC a JSON compacto.

La salida conserva los 13 canales diferenciales (P1..P10, con los bordes de
energia leidos del propio .nc) + el integral >=500 MeV + calidad por muestra,
en un JSON sin dependencias para el consumidor (check_fixtures.py y el
backtesting corren con stdlib en CI hermetico).

Este conversor se ejecuta OFFLINE, en la maquina del desarrollador, igual que
la descarga del .nc (ambos necesitan red/h5py). El CI solo ejecuta
check_fixtures.py, que valida los JSON commiteados.

Dependencias (solo para convertir): numpy, h5py.
    python3 -m venv /tmp/venv && /tmp/venv/bin/pip install numpy h5py

Uso:
    /tmp/venv/bin/python to_json.py entrada.nc salida.json

Flujo completo para (re)generar un fixture:
    1. Descargar el .nc del listing de NGDC (URL en README.md).
    2. Verificar: shasum -a 256 entrada.nc  (debe coincidir con el README).
    3. Convertir con este script.
    4. Actualizar el SHA en README.md si el .nc es nuevo.
    5. python3 check_fixtures.py
"""
import sys, os, json
import numpy as np
import h5py

CH_NAMES = ['P1', 'P2A', 'P2B', 'P3', 'P4', 'P5', 'P6', 'P7',
            'P8A', 'P8B', 'P8C', 'P9', 'P10']


def convert(src, dst):
    with h5py.File(src, 'r') as f:
        # id del fichero para sat/version
        raw = f.attrs.get('id', b'')
        fid = raw.decode() if isinstance(raw, bytes) else str(raw)
        raw = f.attrs.get('platform', b'')
        sat = raw.decode() if isinstance(raw, bytes) else str(raw)
        # tiempo: el nombre de la variable cambio entre versiones de producto
        ts_name = 'L2_SciData_TimeStamp' if 'L2_SciData_TimeStamp' in f else 'time'
        ts = f[ts_name][:]
        # sensor con menos huecos en el integral (el otro suele tener NaN por
        # yaw flip o estar apagado)
        it_all = f['AvgIntProtonFlux'][:].copy()
        it_all[it_all < 0] = np.nan
        s = int(np.argmin(np.isnan(it_all).sum(axis=0)))
        integ = it_all[:, s]
        fl = f['AvgDiffProtonFlux'][:, s, :].copy()
        lo = f['DiffProtonLowerEnergy'][s]
        hi = f['DiffProtonUpperEnergy'][s]
        nvalid = f['DiffValidL1bSamplesInAvg'][:, s, :].copy()
        yf_name = 'YawFlipFlag' if 'YawFlipFlag' in f else 'yaw_flip_flag'
        yaw = f[yf_name][:]
        int_nvalid = f['IntValidL1bSamplesInAvg'][:, s].copy()

    # Redondear: float32 trae ~7 digitos; 6 decimales bastan y el JSON queda
    # mucho mas compacto (los flujos van de ~1e-6 a ~1e3 pfu/keV).
    diff = np.round(fl.astype(np.float64), 6)
    integ_r = np.round(integ.astype(np.float64), 6)

    # _FillValue (-1e31) -> null
    def clean(a):
        a = a.copy()
        a[~np.isfinite(a) | (a < -1e30)] = np.nan
        return a
    diff = clean(diff)
    integ_r = clean(integ_r)

    out = {
        "product": "sgps-l2-avg5m",
        "sat": sat,
        "file": fid,
        "sensor": s,
        "n_steps": int(len(ts)),
        "time_offset_s": int(ts[0]) if len(ts) else None,
        "time_step_s": int(ts[1] - ts[0]) if len(ts) > 1 else 300,
        "channels": [{"name": CH_NAMES[i], "lo_keV": float(lo[i]), "hi_keV": float(hi[i])}
                     for i in range(13)],
        "integral_500_keV": integ_r.tolist(),
        "diff": diff.tolist(),
        "samples_in_avg": nvalid.tolist(),
        "int_samples_in_avg": int_nvalid.tolist(),
        "yaw_flip": yaw.tolist(),
    }
    with open(dst, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'), allow_nan=True)
    print(f"{dst}: {sat} sensor {s} {len(ts)} pasos, {os.path.getsize(dst)} bytes")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit("uso: to_json.py entrada.nc salida.json")
    convert(sys.argv[1], sys.argv[2])
