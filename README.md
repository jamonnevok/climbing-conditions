# Climbing Conditions Advisor

A free, mobile-friendly static web app that turns the **latest ECMWF IFS forecast** and **IRM/KMI station observations** into:

- a **bouldering-conditions score out of 10** (hourly, per day, best 2–4 h window, 5-day outlook), with the main limiting factors ("Limited by humidity and wet rock."), and
- short, generic, **rule-based crag-selection tips** in English and French ("Humid and still: look for higher, windier, more exposed spots…").

The app knows no individual crags. It scores a **region** and gives advice you apply to the crag you are considering. Belgium (Namur area) ships first; the architecture is ready for France.

Everything is free and runs on GitHub: source in a repository, data processing in **GitHub Actions**, website on **GitHub Pages**. There is no server, no database, no account, and no runtime AI.

---

## Contents

1. [How it works](#1-how-it-works)
2. [Deploy on GitHub (step by step)](#2-deploy-on-github-step-by-step)
3. [Using the app](#3-using-the-app)
4. [How updates work](#4-how-updates-work)
5. [Run everything locally](#5-run-everything-locally)
6. [Troubleshooting failed updates](#6-troubleshooting-failed-updates)
7. [Configuration: regions, scoring, tips](#7-configuration-regions-scoring-tips)
8. [Scoring model](#8-scoring-model)
9. [Calibration and back-testing](#9-calibration-and-back-testing)
10. [Extending to France](#10-extending-to-france)
11. [Data sources, verification status and licences](#11-data-sources-verification-status-and-licences)
12. [Known limitations](#12-known-limitations)
13. [Repository layout](#13-repository-layout)

---

## 1. How it works

```
ECMWF open data ─┐                    ┌─ compact JSON ──► GitHub Pages ──► browser
                 ├─► GitHub Actions ──┤   (≈70 KB/region)
IRM/KMI AWS ─────┘   Python pipeline  └─ calibration CSV ──► history/ (in git)
```

The pipeline runs in stages. Each stage is a separate workflow step, so a failure shows exactly where it happened:

| Stage | Command | What it does |
|---|---|---|
| 1 | `fetch-previous` | Loads the inputs behind the currently published site. A model run that was already processed is reused, not downloaded again. |
| 2 | `fetch-forecast` | Finds the newest ECMWF IFS run that covers the next 120 h and downloads only 7 variables. Falls back to Open-Meteo if needed. |
| 3 | `fetch-observations` | Gets the last 72 h of IRM/KMI 10-minute data from the nearest stations, aggregated to hourly. Falls back to Open-Meteo past hours, labelled "modelled". |
| 4 | `site` | Copies the static frontend and translations into `dist/`. |
| 5 | `score` | Builds one hourly timeline (observed past + forecast), then computes wetness, scores, best windows and tips, and writes JSON. |
| 6 | `validate` | Sanity-checks the generated JSON. If it fails, nothing is deployed. |
| 7 | `history` | Appends compact calibration rows (CSV). |

Raw GRIB files are downloaded to a temporary folder and deleted as soon as they are decoded. They are never committed or published.

---

## 2. Deploy on GitHub (step by step)

You need a free GitHub account. Total time: about 15 minutes.

### 2.1 Create the repository
1. Sign in at github.com, click **+** (top right) → **New repository**.
2. Name it, for example `climbing-conditions`.
3. Choose **Public**. GitHub Pages and unlimited Actions minutes are free only for public repositories on the Free plan.
4. Leave "Add a README" **unticked**. Click **Create repository**.

### 2.2 Upload the project
**Option A: with Git (recommended).** In a terminal, inside the unzipped project folder:
```bash
git init
git add .
git commit -m "Initial version"
git branch -M main
git remote add origin https://github.com/<your-user>/climbing-conditions.git
git push -u origin main
```
**Option B: in the browser.** On the empty repository page, click **uploading an existing file** and drag in **all files and folders**. Browsers often skip hidden folders, so check afterwards that `.github/workflows/` exists in the **Code** tab. If it is missing, create each workflow with **Add file → Create new file**, typing the full name (for example `.github/workflows/update-weather.yml`) and pasting the content.

### 2.3 Repository settings
1. **Settings → Actions → General**:
   - "Actions permissions": **Allow all actions and reusable workflows**.
   - "Workflow permissions": select **Read and write permissions**. This lets the workflows commit the small history files. Click **Save**.
2. **Settings → Pages**: under "Build and deployment" → **Source**, choose **GitHub Actions**.

No secrets or API keys are needed. Every data source is anonymous.

### 2.4 Enable GitHub Actions
Open the **Actions** tab. If GitHub shows a button asking you to enable workflows, click it. You should see these workflows in the left sidebar: `update-weather`, `deploy-site`, `daily-history`, `tests`, `step0-verify`.

### 2.5 Run the first weather update
**Actions → update-weather → Run workflow → Run workflow** (branch `main`). After a few seconds, refresh the page and a run appears.

### 2.6 Check that it worked
Open the run. Both jobs, **build** and **deploy**, should have a green ✔. Expect about 3–6 minutes; the ECMWF download is about 125–150 MB of temporary data. The **deploy** job box shows the site URL.

### 2.7 Find the website
The URL is `https://<your-user>.github.io/<repository-name>/`, for example `https://jdoe.github.io/climbing-conditions/`. It is also shown in **Settings → Pages**. The very first deployment can take a minute or two to appear.

### 2.8 Diagnose a failed run
Click the red ✖ run, then the failed job, then the step with ✖. See [Troubleshooting](#6-troubleshooting-failed-updates). A failed update **never takes the site offline**: the last successful version stays published.

### 2.9 Update the app later
Edit files (on github.com with the ✏️ pencil, or locally followed by `git push`). Any push to `main` that changes code or configuration runs **deploy-site**. That workflow runs the tests, then **re-scores the last downloaded weather inputs** with your new code or config and redeploys, without a new weather download. Changes to `*.md` files and `history/` do not trigger a deployment.

---

## 3. Using the app

- **Region / Mode / Language** controls are at the top. Your choices are stored in your browser only.
  - **Comfort** mode: ideal temperature about 8–18 °C.
  - **Performance** mode: ideal temperature about 2–12 °C, and stricter on humidity and wetness, for best friction.
- **Now**: the score for the current hour, with its limiting factors.
- **Tips**: for the selected day. Click a day in the outlook to switch.
- **Hourly chart**: solid bars are observed hours, lighter bars are forecast hours. Blue dots mark rain. The dashed line is "now". Hover or tap a bar for details.
- **Data**: shows the model run, the latest observation, the station, the last update time, and the source of every variable.
- A banner always shows the **real age of the data**. If the data is older than 6 h, it asks you to refresh.

### Optional "Refresh" button
GitHub only runs a workflow for someone who is authenticated. To refresh from the app:
1. GitHub → your avatar → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Repository access**: *Only select repositories* → your climbing repository.
3. **Permissions → Repository permissions → Actions: Read and write**. Metadata: read is added automatically.
4. Set an expiry date, generate the token, and copy it.
5. In the app, click ⚙, paste the token, check the repository (`owner/name`, filled in automatically on github.io), and click **Save**.

A **Refresh data** button then appears. It starts `update-weather` through the GitHub REST endpoint `POST /repos/{owner}/{repo}/actions/workflows/update-weather.yml/dispatches` and reloads the data when the new version is live.

The token is stored **only in your browser's localStorage**. It is never put in the code or the generated files. Anyone else who opens the site just sees the last published data. Use a token limited to this one repository, and revoke it on GitHub if your device is lost.

---

## 4. How updates work

| Workflow | Trigger | Downloads | Deploys | Commits |
|---|---|---|---|---|
| `update-weather` | **Manual** (Actions tab or Refresh button) | ECMWF run (only if not already processed) + 72 h of IRM data | yes | history rows, only if new |
| `deploy-site` | push to `main` (code/config) or manual | none (re-scores the last inputs) | yes | no |
| `daily-history` | daily 05:17 UTC + manual | **IRM observations only** (48 h, a few hundred KB) | **no** | observed history |
| `tests` | pull requests, manual | none | no | no |
| `step0-verify` | manual | small samples from every source | no | no |

- **No automatic forecast updates.** Data is only refreshed when you ask for it. The one scheduled job is the quiet `daily-history`, which never touches the website and downloads no forecast. You can switch it off with `history.enabled: false` in `config/pipeline.yaml`, or with **Actions → daily-history → ⋯ → Disable workflow**.
- **Run selection.** ECMWF publishes 4 runs a day (00/06/12/18 UTC), each about 7–12 h after its start time. The pipeline picks the newest run whose files reach the step needed to cover the next 120 h, by asking the official client which runs exist. A run that was already processed is reused with no download, while observations are always fetched fresh.
- **Concurrency.** All workflows share the `weather-data` concurrency group, so two runs can never update data or deploy at the same time.
- **Failures.** Deployment only happens after `validate` passes. If ECMWF and Open-Meteo both fail, the previous forecast is reused **with its real run time** and a visible warning. If there is no previous forecast either, the run fails and the old site stays online.
- **Free-tier compatibility.** Standard GitHub-hosted runners are free for public repositories. The site is about 0.2 MB, far below the 1 GB Pages limit. A custom-workflow deployment is not subject to the 10-builds-per-hour Pages limit.
- **60-day rule.** GitHub may disable *scheduled* workflows in repositories with no activity for 60 days. The daily history commit counts as activity. If `daily-history` ever gets disabled, re-enable it in the Actions tab. Manual updates are not affected.

Every published dataset exposes the **ECMWF model run time**, the **latest observation time**, the **processing time**, and the **source of every variable**. You can see them all in the app's *Data* section.

---

## 5. Run everything locally

Requires Python 3.11+ (tested with 3.12). Works on Linux, macOS and Windows; on Windows, use `py` instead of `python` if needed.

```bash
# 1. install dependencies (a virtual environment is recommended)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# 2-4. retrieve the latest weather, process it, generate scores + tips + site
python -m pipeline update          # = fetch-previous, fetch-forecast, fetch-observations,
                                   #   site, score, validate, history

#    ...or stage by stage:
python -m pipeline fetch-previous
python -m pipeline fetch-forecast
python -m pipeline fetch-observations
python -m pipeline site
python -m pipeline score
python -m pipeline validate

# 5. run the tests
python -m pytest -q

# 6. run the frontend locally
python -m http.server 8000 --directory dist
#    then open http://localhost:8000/

# 7. production build = the dist/ folder produced by `site` + `score`
#    (exactly what GitHub Pages serves)
```

- Locally, `fetch-previous` reuses your own `dist/data`, so a second `update` with the same ECMWF run skips the download.
- `python -m pipeline daily-history` runs the quiet observations-only history update.
- `python scripts/step0_verify.py` re-checks every data source and writes `step0_report.json`.
- `python -m pipeline update` also appends to `history/`. Don't commit local history unless you want it.

---

## 6. Troubleshooting failed updates

Open the failed run, then the red step. Error lines are tagged, and each category has its own exit code:

| Symptom (step / log tag) | Exit | Meaning | What to do |
|---|---|---|---|
| **Run tests** fails | – | **Test failure**: code or config is broken | Read the pytest output; fix and push. Nothing was deployed. |
| **Fetch forecast**: `::warning::[ECMWF]` then success | – | **ECMWF download failure**, fallback used | The site shows "Fallback source in use". Retry later. |
| **Fetch forecast**: `::warning::[FALLBACK]` | – | **Fallback-provider failure** (Open-Meteo) | Usually temporary. |
| **Fetch forecast**: `::error::[NO-DATA]` | 50 | Every forecast provider failed and no previous forecast exists | Retry later. The old site stays online. |
| **Fetch observations**: `::warning::[IRM]` | – | **IRM/KMI failure**; fallback or forecast-only spin-up used | Check https://opendata.meteo.be. The app labels it. |
| `::error::[PARSE]` | 20 | **Data parsing failure**: a provider changed its format | Run **step0-verify** and compare with section 11. |
| **Score**: `::error::[SCORING]` | 30 | **Scoring failure** | Usually a config edit (weights, curve). Check `config/scoring.yaml`. |
| **Validate**: `::error::[VALIDATION]` | 40 | Generated data is inconsistent, or tips/translations don't match | The message lists each problem. Nothing was deployed. |
| **Build static frontend** or **Upload GitHub Pages artifact** fails | – | **Frontend build failure** | Check that `frontend/` files exist and that Pages is set to "GitHub Actions". |
| **deploy** job fails | – | **GitHub Pages deployment failure** | Settings → Pages → Source must be "GitHub Actions". Check githubstatus.com, then re-run the failed job. |
| **Commit history** fails | – | Push rejected | Settings → Actions → General → "Read and write permissions". |
| Refresh button: "Could not start the update (HTTP 401/403/404)" | – | Token wrong, expired, without *Actions: write*, or wrong repository | Recreate the token as described in section 3. |

**Golden rule:** whatever fails, the previously deployed site keeps running. The app never shows invented data: missing values stay empty, and stale data is shown with its real timestamp.

---

## 7. Configuration: regions, scoring, tips

All configuration lives in `config/`. Push a change and **deploy-site** re-scores and republishes it within minutes.

### Add a region
Add an entry to `config/regions.yaml`. No code change is needed:
```yaml
  - id: be-ardennes-south
    country: BE
    name: {en: "Southern Ardennes", fr: "Ardenne du sud"}
    lat: 49.90
    lon: 5.40
    timezone: Europe/Brussels
    stations: {max_distance_km: 60, max_candidates: 3, min_completeness: 0.7}
    providers:
      forecast: [ecmwf, openmeteo]
      observation: [irm_aws, openmeteo_past]
```
Then run **update-weather** once so the new region gets data. Stations are discovered dynamically: the nearest active stations within `max_distance_km` are used per variable, and single missing hours are taken from the next station (labelled in the Sources table). The ECMWF file is downloaded **once** for all regions that share a provider chain.

### Tune the score
`config/scoring.yaml` holds the ideal temperature bands and weights per mode, humidity and dewpoint-spread thresholds, the wind curve, the rain thresholds, the wetness/drying coefficients, the caps, the daytime hours, the window lengths, and the driver thresholds. After pushing a change, the site is re-scored with the same weather inputs, so you can compare the effect directly.

### Edit tips
`config/tips.yaml` holds the rules (conditions, priority, translation key, maximum number of tips shown). `config/i18n/en.json` and `fr.json` hold all texts. A test checks that every rule has a translation in both languages and that both files have the same keys.

### Other settings
`config/pipeline.yaml`:
- `forecast.ecmwf.resolution`: `"0p25"` (default) or `"0p1"`. `0p1` is verified, but the download is about 6× larger and arrives about 2 h later.
- Forecast horizon, observation lookback, and history on/off.

---

## 8. Scoring model

Hourly rows use UTC internally. Each row covers `[start, start+1 h)`. Six components are each scaled 0–1:

| Component | Formula (defaults) |
|---|---|
| Temperature | 1 inside the mode's ideal band, then falls linearly to 0 at 10 °C outside it |
| Moisture | 50 % RH score (1 at ≤ 65 %, 0 at ≥ 95 % in comfort mode) + 50 % dewpoint-spread score (0 at ≤ 1 °C, 1 at ≥ 8 °C) |
| Wetness | 1 − W / 1 mm, where W is the wet-rock index (below) |
| Rain | min(1 − P(now)/1 mm, 1 − 0.5·P(next 3 h)/1 mm) |
| Wind | curve: 0 m/s → 0.6, 2–6 m/s → 1, 10 m/s → 0.4, 15 m/s → 0 |
| Sun/cloud | sun factor = measured / clear-sky shortwave. Below the middle of the ideal band sun helps (0.5 + 0.5·f); above it sun hurts (1 − 0.5·f) |

**Score** = 10 × Σ(weight × component) / Σ(weights).
- **Caps:** rain ≥ 0.2 mm/h caps the score at **2**; W ≥ 1 mm caps it at **5**.
- **Drivers:** the components that cost the most points, at least 0.5 points each, up to 2, are named after any cap.

**Wet-rock index:** `W = clip(W + rain − drying, 0, 4 mm)`, where
`drying = 0.15·VPD(kPa)·(1 + 0.15·min(wind, 8)) + 0.3·SW/1000` mm/h.
It starts 72 h back to warm up. If an input is missing, W is carried forward unchanged and that hour gets no score; nothing is guessed.

- **Daily score:** the mean over 08:00–20:00 local time. If fewer than half of those hours are available, it is marked partial.
- **Best window:** the best 2 h mean, extended to 3–4 h if the mean stays within 0.3 of it. For today, only hours from now on count.
- **Drying time:** the hours until W ≤ 0.2 mm.

---

## 9. Calibration and back-testing

`history/` keeps only compact CSVs. No GRIB files, raw downloads or temporary files are stored.

| File | Content | Written by |
|---|---|---|
| `history/observed/<region>/<YYYY-MM>.csv` | Observed hourly temp, dewpoint, RH, rain, wind, radiation, wet index, comfort/performance scores, station, gap-fill flags | `daily-history` (daily) + `update-weather` |
| `history/forecast/<region>/<YYYY-MM>.csv` | Every forecast hour of every **newly processed** ECMWF run: run time, lead time, variables, wet index, scores | `update-weather` |

Rows are de-duplicated and never rewritten.

**Expected growth per region:**
- Observed history: about 70 bytes × 24 h × 365 ≈ **0.6 MB/year**.
- Forecast history: about 11 KB per new run. At 3 manual refreshes a week, that's ≈ **1.7 MB/year**.
- Git compresses CSV well, so the repository should grow by roughly **1–2 MB/year** per region, which stays negligible for years. To trim, delete old monthly files.

**Back-testing ideas:**
- Compare forecast scores at 24/48/72 h lead times with the observed score for the same hour, to measure forecast skill for each lead time.
- Log your own sessions ("rock was dry/greasy at 14:00") and fit `wetness.k_*`, `very_wet_mm` and the moisture thresholds to them.
- Re-scoring with changed parameters only needs the CSVs (all inputs are stored).

---

## 10. Extending to France

The scoring engine, tips, frontend and workflows are country-independent. A French region needs:
1. **Forecast:** nothing new. ECMWF is global; add the region to `regions.yaml`.
2. **Observations:** a French station source must be **researched and verified before use** (not done in v1). Météo-France publishes open observation data, but which dataset to use, how to access it, whether a key is needed, and its field names, units and update delay have **not** been verified. Until then a French region can use `observation: [openmeteo_past]` (modelled, labelled as such). The commented example in `regions.yaml` shows this.
3. **To add the real source:**
   - Implement a class in `providers/` that subclasses `ObservationProvider`, with `fetch(region, start, end) -> HourlySeries` returning hourly rows in the normalised units (see `providers/base.py`).
   - Register it in `providers/registry.py`.
   - Add tests with a real sample response.
   - Add a check to `scripts/step0_verify.py`.
   - If a key is needed, store it as a GitHub Actions **secret** and read it from an environment variable in the provider. Never put it in the code, the JSON or the frontend.

---

## 11. Data sources, verification status and licences

Step 0 (2026-11-12, real requests from a GitHub-hosted runner) **verified**:
- **ECMWF open data:**
  - Anonymous access through `ecmwf-opendata` 0.3.35 and through direct `.index`/byte-range download.
  - Parameters `2t 2d tp 10u 10v tcc ssrd` are available. `tp` and `ssrd` are accumulated from the run start; `2t`/`2d` are in K; `tcc` is 0–1.
  - 3-hourly steps; the 06 UTC run reached 120 h; 0.1° is available.
  - About 3 MB per step for the 7 parameters at 0.25°.
- **IRM/KMI** `opendata.meteo.be` WFS:
  - No key needed. Layers `aws:aws_10min` and `aws:aws_station`.
  - Lowercase field names (`temp_dry_shelter_avg`, `humidity_rel_shelter_avg`, `precip_quantity`, `wind_speed_10m`, `short_wave_from_sky_avg`, …).
  - `CQL_FILTER` works; 14 active stations, the nearest to Namur being Ernage (6459, 17.9 km).
  - About 1.5–2 h latency; data flagged as not yet validated.
- **IRM ALARO** forecast folder is public (4 runs kept). **Disabled in v1**: the file format is not verified.
- **Open-Meteo** `ecmwf_ifs025`: all 7 hourly variables over 144 h.

**Unverified assumptions** (also marked in code comments):
- The IRM `timestamp` marks the *end* of the 10-minute interval.
- IRM units are °C, %, mm per 10 min, m/s and W/m².
- The IRM WFS returns ≤ 72 h of one station without paging.
- The 06/18 UTC runs' range beyond 120 h; the code probes availability instead of assuming it.
- Open-Meteo's `past_days` parameter, and its "preceding hour" convention for precipitation and radiation. Run `step0-verify` to test `past_days`.
- Open-Meteo does not expose the model run time.
- The `aws`/`google` ECMWF mirrors. They are not used by default.

**Licences and attribution:**
- ECMWF open data: CC BY 4.0, © ECMWF.
- IRM/KMI open data: CC BY 4.0.
- Open-Meteo: free for **non-commercial use only**, with limits of 10 000 calls/day; data CC BY 4.0. This app makes at most 2 calls per run, and only when a primary source fails.

Attribution is shown in the app footer. IRM asks users to download each piece of data once and avoid heavy repeated querying; this app makes a few small requests per manual refresh. The unofficial IRM mobile-app API is **not used**: it has no published terms and provides forecasts only.

---

## 12. Known limitations

- **Spatial resolution:** ECMWF IFS at 0.25° means grid cells of about 28 × 18 km at Belgian latitudes (0.1°: about 11 × 7 km). The model cannot resolve valleys, slopes or forest canopy.
- **Local microclimates:** many crag microclimates, **valley fog**, cold-air pooling, sea breezes and **very local showers** are not captured. Observations come from the nearest IRM station: Ernage is 18 km from Namur, at 159 m, in open farmland.
- **Forecast uncertainty:** it grows with lead time, and the score uses a single deterministic forecast with no ensemble spread. Days 4–5 are indicative only.
- **3-hourly forecast interpolation:** short showers and timing within each 3-hour block are smoothed out.
- **Simplified wet-rock/drying model:** one generic exposed surface. It ignores rock type (sandstone vs limestone), aspect, shade, seepage, tree cover and condensation on cold rock. The coefficients are first guesses awaiting calibration (section 9).
- **Sun proxy:** horizontal radiation is used, not radiation on the actual rock face. The tips explain the effect of aspect instead.
- **Provisional observations:** the IRM 10-minute data is not yet quality-controlled. The app drops physically impossible values but can't catch subtle sensor errors.
- **Manual updates:** data is only as fresh as the last time someone pressed the button, and the age is always shown.
- **Unverified assumptions:** listed in section 11.

The app shows conditions only. It gives no safety advice or warnings.

---

## 13. Repository layout

```
.github/workflows/   update-weather, deploy-site, daily-history, tests, step0-verify
pipeline/            CLI (__main__), timeline, wetness, scoring, daily, tips, process, history, resample, physics
providers/           base interfaces, ECMWF, IRM/KMI AWS, Open-Meteo (fallbacks), ALARO (disabled), registry
config/              regions.yaml, scoring.yaml, tips.yaml, pipeline.yaml, i18n/en.json, i18n/fr.json
frontend/            index.html, app.js, style.css, favicon.svg  (no build tooling, no Node)
history/             compact calibration CSVs (committed)
scripts/             step0_verify.py
tests/               unit + end-to-end tests (fake providers, no network)
dist/, work/         generated, git-ignored
```
