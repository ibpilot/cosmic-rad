# ☢️ Cosmic Radiation Flight Calculator

A tool for pilots and cabin crew to estimate cosmic radiation exposure per flight sector. Plan your
monthly schedule, set the flight level for each sector, and get your dose in mSv — compared against
medical imaging references and ICRP regulatory limits. It also estimates the extra dose from
**solar particle events (SPEs)** when the GOES archive covers the flight window. Export a
professional PDF report.

**Live app → [ibpilot.github.io/cosmic-rad](https://ibpilot.github.io/cosmic-rad)**

---

## Features

- **Monthly flight planner** — add every sector of the month, each with its own flight level
  (FL310–FL410), number of legs and departure date/time (UTC). Flights are saved automatically per
  month in `localStorage`; the app opens on the current month.
- **Solar cycle adjustment** — real monthly **heliocentric potential** from the FAA (2011–present,
  auto-updated). Dose rates are interpolated from a precomputed dose grid generated offline with
  **CARI-7A** (FAA CAMI). Manual presets available (solar min/mean/max).
- **Solar particle events (SEP)** — a per-flight **“☀ Check solar activity”**: given the departure
  date and time it reads the GOES archive, fits a proton spectrum and returns a **dose range** for
  that flight, on top of the galactic (GCR) dose. Pending or failed data is **never** shown as zero.
- **Space-weather semaphore** — live GOES ≥10 MeV proton flux from NOAA SWPC, shown as the NOAA
  S-scale (S0–S5), with an info sheet explaining what it is *and what it is not* (it is not a dose).
- **Route import (FPL)** — paste a flight-plan route (`KJFK31L.JFK5.BDR..MAD..HFD..`) and it is
  resolved against a local **fix database** (184k+ named fixes, lazy-loaded). The dose is then
  integrated over the real path at the selected flight level.
- **Level steps** — optional field for the plan's step climbs
  (`F370 4730N04000W/F330 45N020W/F390 BANAL/…`); each segment is computed at its own level and the
  FL selector locks.
- **Outbound + return pairs** — “Add return” groups both flights into one collapsible card. Collapse
  is an explicit **Collapse** button; it never collapses on its own.
- **Batch incorporate** — “Add all” incorporates every available SEP estimate for the visible month
  in one action, with a confirmation summary and a single undo.
- **Dose comparisons** — monthly and annual dose vs. chest X-ray, mammography, CT scan, PET-CT,
  natural background and the ICRP crew limit (20 mSv/year).
- **ICRP progress ring**, a **pregnancy section** (ICRP 1 mSv limit) and an optional **aeronautical
  career dose** estimate.
- **PDF report** and **backup export/import**.
- **Airport database** — 7,600+ airports from a local OpenFlights copy (ODbL 1.0), with a curated
  160-airport fallback.
- **Single file, ES/EN** — no build step, no backend; React 18 is inlined.

---

## How it works

### Galactic cosmic radiation (GCR)

Dose estimation is based on a **precomputed dose-rate grid generated offline with CARI-7A**
(FAA Civil Aerospace Medical Institute). The grid is indexed by **vertical cutoff rigidity**
(0–18 GV, 0.25 GV step), **altitude** (8–13 km, 0.5 km step) and **heliocentric potential**
(300–1200 MV), and interpolated at runtime.

Geographic position enters through the **vertical cutoff rigidity**, computed from the 1°×1°
geomagnetic-cutoff map that ships with CARI-7A. So longitude matters as much as latitude: at the
same map latitude the shielding can be very different (at 50°N it is about five times lower over
Canada than over Kamchatka, which is why North Atlantic routes are the highest-dose ones). For dates
from 2010 onwards this is the exact same map CARI-7A uses. Flight time is estimated at 830 km/h
average ground speed.

The solar state uses the **real monthly heliocentric potential** published by the FAA for the
flight's month (automatic mode), or a manual preset.

If the grid is missing (e.g. first load), the app falls back to the previous simplified EURADOS
altitude/latitude band model:

| Latitude | Dose rate at FL350 (solar neutral) |
|---|---|
| < 15° (equatorial) | ~1.5 µSv/h |
| 15–30° | ~2.2 µSv/h |
| 30–45° (mid-latitude) | ~3.5 µSv/h |
| 45–60° | ~4.8 µSv/h |
| > 60° (polar) | ~6.0 µSv/h |

### Solar particle events (SEP)

When a flight has a departure date and time (UTC), the app can add the SEP contribution:

- **Detection** — a fixed **12 h baseline before departure** (median + 3σ using a scaled MAD); a
  trigger in the hardest channels (P9+P10 or the ≥500 MeV integral) with confirmation in the wider
  P8+ band, requiring three consecutive 5-minute samples.
- **Spectrum** — the 13 GOES differential channels (plus the ≥500 MeV integral) are fitted with a
  power law and a double power law. Both members are extrapolated above the last measured channel
  with a slope no softer than E⁻³. If more than 10 % of the dose would come from the unmeasured
  tail, the model returns **no figure** rather than a misleading number.
- **Range** — the min–max of the ensemble, always widened to at least a factor 3. It is a spread of
  spectral shapes, **not** a confidence interval.
- **Integration** — each member is integrated along the route with a nodal **response operator built
  from CARI-7A** (cutoff rigidity × altitude × energy).
- **Data** — the GOES archive is served from the separate public repository
  **[cosmic-rad-data](https://github.com/ibpilot/cosmic-rad-data)** via GitHub Pages: SWPC days
  collected by a scheduled GitHub Action, plus the **NCEI SGPS L2 avg5m** historical archive.
- **Coverage** — the archive starts on **2025-09-11**, and NCEI is published with about **2 days of
  latency**. If the flight window is not fully covered (a flight today, or a gap), the occurrence
  stays **pending** — never zero: “not known yet” is not “measured zero”.

**Model calibration:** GLE69–71 (Sato et al. 2018) and GLE72 (Copeland et al. 2018 / PANDOCA);
GLE73 is the calibrating event and GLE74 is the hold-out, checked against PANDOCA (Schennetten et
al. 2024). The scale rests on essentially one calibrating event, and the result is **not certified
dosimetry**.

### Route-based dose (FPL)

Without a route, the dose is estimated over the great-circle path between origin and destination at
the selected flight level. When you import a route, the dose is integrated over the **real path**,
segment by segment, with the same CARI-7A rate table:

- **FPL route** — waypoints are resolved against the local fix database (lazy-loaded once;
  unresolved fixes are skipped with a warning). Each leg uses the altitude of the selected flight
  level, or the plan's **level steps** if provided.
- **Level steps** (optional field) — `F370 4730N04000W/F330 45N020W/F390 BANAL/…` means the flight
  climbs/descends to the listed flight level at each waypoint. Each segment is then computed at its
  own altitude and the FL selector locks.

---

## Dose reference table

| Reference | Dose |
|---|---|
| Dental X-ray | 5 µSv |
| Chest X-ray | 20 µSv |
| Mammography | 400 µSv |
| Chest CT scan | 7,000 µSv (7 mSv) |
| PET-CT | 14,000 µSv (14 mSv) |
| Natural background / year (Spain) | 2,400 µSv (2.4 mSv) |
| ICRP crew limit / year | 20,000 µSv (20 mSv) |
| ICRP limit — pregnancy (total) | 1,000 µSv (1 mSv) |

---

## Scientific sources

- **CARI-7A (FAA CAMI)** — dose-rate grid and SEP response operator: cosmic-ray shower transport
  (MCNPX 2.7.0), geomagnetic cutoffs, heliocentric-potential modulation.
  [FAA radiobiology](https://www.faa.gov/data_research/research/med_humanfacs/aeromedical/radiobiology/cari7)
- **FAA monthly heliocentric potential** — `MV-DATES` file, auto-updated monthly by the pipeline
- **NOAA SWPC (GOES)** — live ≥10 MeV proton flux and archived differential/integral proton channels
- **NOAA NCEI (SGPS L2 avg5m)** — historical GOES archive used for the SEP model
- **NMDB (Neutron Monitor Database)** — neutron-monitor profiles used for GLE calibration
- **Sato et al. 2018** — GLE69–71 reference doses (<https://doi.org/10.1029/2018SW001873>)
- **Copeland et al. 2018** — GLE72 reference (PANDOCA) (<https://doi.org/10.1029/2018SW001917>)
- **Schennetten et al. 2024 (PANDOCA)** — GLE74 published reference
  (<https://doi.org/10.3389/fspas.2024.1498910>)
- **ICRP Publication 103** (2007) — the 2007 Recommendations of the International Commission on
  Radiological Protection
- **EURADOS Report 2004-1** — fallback altitude/latitude band model
- **UNSCEAR 2008** — Sources and Effects of Ionizing Radiation, Annex B (natural radiation sources)
- **Mewaldt R.A. (2010)** — galactic cosmic ray composition and energy spectra (solar cycle
  modulation estimates)
- **Real Decreto 783/2001** — Reglamento sobre protección sanitaria contra radiaciones ionizantes
  (Spain)
- **Euratom Directive 2013/59** — basic safety standards for protection against ionising radiation
- **OpenFlights** — airport database (ODbL 1.0; see `data/airports.ATTRIBUTION.md`)

---

## Disclaimer

This tool provides **orientation estimates only**. It is not a certified dosimetry system, and the
SEP figure in particular is experimental. Results should not replace official dosimetry tools such
as:

- **CARI-7** (FAA Civil Aerospace Medical Institute)
- **SIEVERT** (EURADOS online calculator)
- **EPCARD** (European Programme Package for the Assessment of Cosmic Radiation Dose)

For official occupational radiation surveillance, consult your company's Occupational Health
Service.

---

## Privacy

All data stays in your browser: schedules, routes and doses are stored only in `localStorage` on the
device you use, and nothing is uploaded. The only network calls are plain `GET`s to public data —
NOAA SWPC (`services.swpc.noaa.gov`) and the `cosmic-rad-data` GitHub Pages site — plus the app's own
files. Two caveats:

- **Shared origin on GitHub Pages.** GitHub serves every project of an account under the same origin
  (`user.github.io`), so a script running on *another* project of the same account could read this
  app's `localStorage`. Don't enter flight data on shared or public devices.
- **Data is device-local.** Clearing the browser's site data removes your schedules — use the backup
  export/import buttons to keep a copy.

---

## Limitations

- The GCR grid is a **monthly-average** model (heliocentric potential); short-term solar-cycle
  variation is not modelled. SPEs **are** modelled, but only when the GOES archive covers the
  window, and there is no archive before **2025-09-11**.
- The SEP range is a spread of spectral shapes widened to a factor 3, **not** a confidence interval,
  and its calibration rests on essentially one event.
- Ground speed is fixed at 830 km/h — actual flight time may differ.
- The geomagnetic-cutoff map is static: CARI-7A 4.2.0 (October 2021) still ships the 2010 map, which
  adds a few percent of uncertainty to any CARI-7A-based calculation, this one included.
- Terrestrial background radiation at altitude (e.g. high-altitude airports such as Bogotá or Quito)
  is not included.
- **No offline mode**: the airport/fix files and the solar archive are fetched live.

---

## Local development

No build step is required. Serve the folder over HTTP (some browsers block `fetch` on `file://`,
in which case the app falls back to the curated airport list):

```bash
git clone https://github.com/ibpilot/cosmic-rad.git
cd cosmic-rad
python3 -m http.server 8765
# open http://localhost:8765
```

React 18 and ReactDOM are inlined in the single file (no CDN). An internet connection is only needed
for the solar archive (SWPC/NCEI) and the space-weather semaphore; airports and fixes are served
from the repo itself.

### Testing

The regression suites run headless in Node and Python (no browser, no network, no third-party deps):

```bash
node tools/tests/bugs_test.js            # app regression suite (dose, routes, NCEI, solar check, backup)
node tools/tests/sep_test.js             # SEP model runtime (detection, ensemble, route)
node tools/tests/grid_test.js            # dose grid / cutoff-rigidity suite
node tools/tests/sep_operator_test.js    # SEP response operator (Node)
cd tools && python3 -m unittest -v       # CARI-7A pipeline, GLE calibration, operator assembly
```

The embedded artifacts are checked separately:

```bash
python3 tools/tests/check_sep_operator.py --index index.html --require-43
python3 tools/embed_sep_runtime.py --check
```

All of it runs automatically on every push to `main` and on pull requests via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

### Grid and operator generation (CARI-7A)

Both artifacts are generated offline with the real CARI-7A binary (FAA) and committed by the bot:

- **Dose grid** — [`.github/workflows/generate-dose-grid.yml`](.github/workflows/generate-dose-grid.yml)
  (manual dispatch): fidelity self-test, grid generation in parallel across 10 heliocentric
  potentials, monotonicity validation, then it embeds the new `DOSE_GRID` block into `index.html`.
  A monthly schedule refreshes the `HP_MONTHS` heliocentric potentials from the FAA.
- **SEP response operator** — [`.github/workflows/generate-sep-grid.yml`](.github/workflows/generate-sep-grid.yml)
  (manual dispatch): builds the nodal operator (`sep-2`) and runs the blocking gates against CARI-7A
  (unit gate, linearity, full-grid and off-grid reproduction, monotonicity) before publishing.
  The runtime that consumes it lives in `tools/sep_operator_runtime.js` (inlined into `index.html`).

While the grid is absent (`DOSE_GRID.data = null`), the app uses the simplified EURADOS band model as
fallback.

---

## Contributing

Pull requests welcome. If you find a missing airport, an incorrect dose factor, or want to add a
language — open an issue or submit a PR.

---

## License

MIT — free to use, modify, and distribute.

---

*Built with React 18 · Airport data: [OpenFlights](https://openflights.org/data.html) (ODbL 1.0) ·
Radiation model: CARI-7A (FAA) + GOES (NOAA SWPC/NCEI)*
