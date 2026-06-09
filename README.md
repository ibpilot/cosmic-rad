# ☢️ Cosmic Radiation Flight Calculator

A tool for pilots and cabin crew to estimate cosmic radiation exposure per flight sector. Input your monthly schedule, select flight level and solar cycle, and get your dose in mSv — compared against medical imaging references and ICRP regulatory limits. Export a professional PDF report.

**Live app → [ibpilot.github.io/cosmic-rad](https://ibpilot.github.io/cosmic-rad)**

---

## Features

- **Monthly flight planner** — add all your sectors for the month, with individual flight level (FL310–FL410) and number of legs per sector
- **Per-flight FL selector** — fine-tune radiation dose per sector, not just globally
- **Solar cycle adjustment** — accounts for galactic cosmic ray flux variation (solar minimum / mean / maximum). Currently near Cycle 25 solar maximum (~2025)
- **Dose comparisons** — your monthly and annual dose vs. chest X-ray, mammography, CT scan, PET-CT, natural background, and ICRP crew limit (20 mSv/year)
- **ICRP progress ring** — visual indicator of how much of your annual regulatory limit you've used
- **Pregnant crew toggle** — dedicated section with ICRP limit for pregnancy (1 mSv total), monthly budget bar, and regulatory references (RD 783/2001, AESA)
- **Aeronautical career dose** — toggle to estimate cumulative lifetime exposure (flight dose only, separate from natural background)
- **Month-by-month history** — navigate between months, plan ahead up to 12 months, full history saved automatically via localStorage
- **Auto-save** — flights saved automatically per month; restored on next visit
- **Full airport database** — loads 7,600+ airports from OpenFlights on startup (IATA + ICAO codes, name search). Falls back to ~160 curated airports if offline
- **PDF export** — professional report with sector breakdown, dose equivalences, ICRP usage, and career summary
- **PWA-ready** — install to home screen on iOS, Android, or desktop for offline use
- **Single file** — no framework, no build step, no backend. One `.html` file

---

## How it works

Dose estimation is based on the EURADOS generalized altitude/latitude model:

| Latitude | Dose rate at FL350 (solar neutral) |
|---|---|
| < 15° (equatorial) | ~1.5 µSv/h |
| 15–30° | ~2.2 µSv/h |
| 30–45° (mid-latitude) | ~3.5 µSv/h |
| 45–60° | ~4.8 µSv/h |
| > 60° (polar) | ~6.0 µSv/h |

**Flight level factors** (relative to FL350):
- FL310: ×0.82 | FL350: ×1.00 | FL390: ×1.18 | FL410: ×1.30

**Solar cycle factors** (mid/high latitudes):
- Solar minimum: ×1.18 | Mean: ×1.00 | Solar maximum: ×0.87

Route effective latitude is computed via the great-circle midpoint (Clairaut's formula). Flight time is estimated at 830 km/h average ground speed.

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

- **EURADOS Report 2004-1** — Cosmic radiation exposure of aircraft crew: compilation of measured and calculated data
- **ICRP Publication 103** (2007) — The 2007 Recommendations of the International Commission on Radiological Protection
- **UNSCEAR 2008** — Sources and Effects of Ionizing Radiation, Annex B (natural radiation sources)
- **Mewaldt R.A. (2010)** — Galactic cosmic ray composition and energy spectra (solar cycle modulation estimates)
- **Real Decreto 783/2001** — Reglamento sobre protección sanitaria contra radiaciones ionizantes (Spain)
- **Euratom Directive 2013/59** — Basic safety standards for protection against ionising radiation

---

## Disclaimer

This tool provides **orientation estimates only**. It is not a certified dosimetry system. Results should not replace official dosimetry tools such as:

- **CARI-7** (FAA Civil Aerospace Medical Institute)
- **SIEVERT** (EURADOS online calculator)
- **EPCARD** (European Programme Package for the Assessment of Cosmic Radiation Dose)

For official occupational radiation surveillance, consult your company's Occupational Health Service.

---

## Limitations

- Dose rates are generalized by latitude band, not computed from actual atmospheric models
- Does not account for terrestrial background radiation at altitude (e.g. high-altitude airports like Bogotá or Quito)
- Ground speed is fixed at 830 km/h — actual flight time may differ
- Solar cycle modulation factors are estimates based on published literature, not real-time solar activity data
- Solar Particle Events (SPEs / solar flares) are not modeled — these rare events can temporarily increase dose significantly on polar routes

---

## Local development

No build step required. Open `index.html` directly in any modern browser:

```bash
git clone https://github.com/ibpilot/cosmic-rad.git
cd cosmic-rad
open index.html
```

React 18 and Babel are loaded from CDN. An internet connection is required on first load to fetch the full airport database from OpenFlights. Subsequent visits use the browser cache.

---

## Contributing

Pull requests welcome. If you find a missing airport, incorrect dose factor, or want to add a language — open an issue or submit a PR.

---

## License

MIT — free to use, modify, and distribute.

---

*Built with React 18 · Airport data: [OpenFlights](https://openflights.org/data.html) · Radiation model: EURADOS / ICRP 103*
