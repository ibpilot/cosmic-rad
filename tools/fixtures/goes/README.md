# Fixtures GOES SGPS — eventos SEP y días tranquilos

Fixtures del modelo SEP (plan `sep-goes-model`, T2). Son la **única fuente de
datos del backtesting**: el CI es hermético y no toca la red. Cada fichero es
un JSON convertido de un NetCDF **SGPS L2 avg5m** de NCEI/NGDC (producto real:
13 canales diferenciales P1..P10 + integral ≥500 MeV).

## Formato

Cada `*.json` conserva, por día de 288 muestras de 5 min:

- `product`, `sat` (`g16`/`g18`), `file` (nombre del .nc original), `sensor`.
- `time_offset_s` / `time_step_s` (300 s): reconstrucción del eje temporal.
- `channels`: los 13 canales con sus bordes `lo_keV`/`hi_keV` **leídos del
  propio .nc** (varían ligeramente entre versiones de producto).
- `integral_500_keV`: el canal integral ≥500 MeV (el único canal integral).
- `diff`: flujo diferencial `[288][13]` en `protons/(cm² sr keV s)`.
- `samples_in_avg`, `int_samples_in_avg`, `yaw_flip`: calidad por muestra.

Los huecos (`_FillValue`) se convierten a `null`. El flujo nunca es negativo.
La conversión la hace `to_json.py` (redondeo a 6 decimales); el SHA-256 que
figura abajo es **del .nc original**, para auditar que el JSON deriva del
archivo exacto que se descargó.

## Selección de los días

Los controles SEP no-GLE se eligieron barriendo **todos** los días de
2022-2025 (1461 NetCDF) por exceso en los canales duros (P8+ = diferenciales
~83-404 MeV, P9+P10 e integral ≥500 como referencia). Detalle de la selección
y del hallazgo sobre la insensibilidad del canal ≥500 MeV: ver el commit y
`contexto.md` (Q111).

- **GLE73 / GLE74**: los dos GLE del rango con instrumentación GOES-16/18
  homogénea (Q101, Q108).
- **3 intensos**: los SEP no-GLE con mayor exceso en canales duros del periodo,
  con espectros de dureza distinta (2024-03-23 blando, 2024-06-08 y 2024-10-09
  duros). Día previo tranquilo en los tres: el exceso es del propio día.
- **2 marginales**: exceso sostenido (≥3 muestras consecutivas sobre mediana
  12 h + 3 MAD) en P8+, justo por encima del umbral — ejercitan la frontera de
  detección y el modo "detectado sin cifra defendible".
- **6 tranquilos / pre-evento**: sin exceso en ninguna banda, o solo al final
  del día. Dos pegados a los GLE (2021-10-27 antes de GLE73 con fondo alto,
  2024-05-08/09 antes de GLE74) y 2024-05-10 (pre-GLE74: las primeras ~18 h
  tranquilas, el evento arranca al final del día) como **baseline previo al
  evento** para el detector de T7. Dos lejos de eventos (2022-06-15,
  2023-01-15).

Nota (Q111, resuelta en T2): el detector de T7 usará como baseline las 12 h de
un periodo tranquilo **anterior al inicio del evento**, no una mediana rodante
intra-día. Con baseline intra-día, los eventos que duran >12 h o empiezan antes
del amanecer (GLE74, los intensos de 2024) son invisibles; con el día previo
tranquilo se detectan con margen enorme. Por eso 2024-05-10 y 2021-10-27 viajan
como fixtures.

## Procedencia

URL base: `https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/{g16|g18}/l2/data/sgps-l2-avg5m/{YYYY}/{MM}/{fichero}`
Descarga: 2026-09-05.

| fichero | descripción | satélite | .nc original | sha256 del .nc |
|---|---|---|---|---|
| g16_2021-10-28.json | GLE73 (evento de calibración) | g16 | sci_sgps-l2-avg5m_g16_d20211028_v2-0-0.nc | b631e5578235381e25d498a36b70f6cb1af48369e3b39acccda9301360d438bf |
| g18_2024-05-11.json | GLE74 (evento de calibración) | g18 | sci_sgps-l2-avg5m_g18_d20240511_v3-0-2.nc | 050920f03057d478f361ea662cc5d8a50bf20261e449c9df02637b7bc5777d81 |
| g18_2024-03-23.json | SEP intenso (control, blando) | g18 | sci_sgps-l2-avg5m_g18_d20240323_v3-0-2.nc | 5e377455e3e21cc22a9c8885fca4c940404e6a4070ab559acd815bff0fb69c26 |
| g18_2024-06-08.json | SEP intenso (control, duro) | g18 | sci_sgps-l2-avg5m_g18_d20240608_v3-0-2.nc | 257a192ce3441feb609301e5c1a87ce013f69e17087e6cef6751f29e6c7fcd43 |
| g18_2024-10-09.json | SEP intenso (control, duro) | g18 | sci_sgps-l2-avg5m_g18_d20241009_v3-0-2.nc | 8fcefb3fd02a572fc910e25577c5179de890753acad42530e10fdb275799bec7 |
| g18_2024-09-01.json | SEP marginal (control) | g18 | sci_sgps-l2-avg5m_g18_d20240901_v3-0-2.nc | f1001ce8984e31a9a7e29649a54814bfc19eab86e8674d4f92fef42c076f417f |
| g18_2024-12-08.json | SEP marginal (control) | g18 | sci_sgps-l2-avg5m_g18_d20241208_v3-0-2.nc | 6688222232aa8e9a99f7a8bea780fb96fcfd13f1679f587b8773062a9c745cf3 |
| g16_2021-10-27.json | día tranquilo (antes de GLE73) | g16 | sci_sgps-l2-avg5m_g16_d20211027_v2-0-0.nc | 70bc5ca85ba4a26a0ab04fb4a7c1d533ca146d4b27f4f1f38c967c4835f997f9 |
| g18_2024-05-08.json | día tranquilo (antes de GLE74) | g18 | sci_sgps-l2-avg5m_g18_d20240508_v3-0-2.nc | 90e0f60513eb0a1d217bb3ccceea2ce4c9f8364b382799e8e93eb6b5c925281f |
| g18_2024-05-09.json | día tranquilo (antes de GLE74) | g18 | sci_sgps-l2-avg5m_g18_d20240509_v3-0-2.nc | 806344d55daa0432bff1c7a570e4e06f8d4f221f7977631a0eb35b6936541fab |
| g18_2024-05-10.json | pre-GLE74 (baseline previo al evento) | g18 | sci_sgps-l2-avg5m_g18_d20240510_v3-0-2.nc | c4845f6da65b090525cac560037bc038dde9850a7334dbf76d4b4c944c59cb02 |
| g16_2022-06-15.json | día tranquilo (lejos de eventos) | g16 | sci_sgps-l2-avg5m_g16_d20220615_v3-0-0.nc | 5f7dcf2f4df10c2a8c3a7af474dbfd469880baa22cf112442d57a34b400f7c9f |
| g16_2023-01-15.json | día tranquilo (lejos de eventos) | g16 | sci_sgps-l2-avg5m_g16_d20230115_v3-0-0.nc | b0b49641988237642f6d07b0fa7e61ad70f92406fec46fe2a9685ce5145e41b9 |

Nota sobre versiones de producto: **no son constantes por satélite**. g16 usa
v2-0-0 en 2021, v3-0-0 en 2022-2023 (transición abr-2022), v3-0-1 (abr-oct
2023) y v3-0-2 (oct-2023 en adelante); g18 usa v3-0-2 desde 2024. El conversor
lee la versión real de cada mes del listing de NGDC; el barrido probó ambas
versiones en los meses de transición.

## Validación

```bash
python3 tools/fixtures/goes/check_fixtures.py
```

Comprueba: 13 canales presentes, 288 pasos, cadencia 300 s, integral ≥500 sin
huecos, sin valores negativos, y coherencia de SHA-256 del .nc (si el .nc está
presente en local). Falla si falta cualquiera de los 13 ficheros.
