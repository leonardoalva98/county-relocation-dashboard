# County Relocation Dashboard

> **Business question:** Which U.S. county is the best fit for me to relocate to?  
> This pipeline integrates demographics, air quality, and crime data at the **county level**
> into three Power BI dashboard pages, letting you filter and rank all ~3,000 U.S. counties
> across the dimensions that matter most to you.

---

## Architecture & Data Flow

```
[Census ACS API]  ──► ingest_census.py ──► data/processed/census.csv ──┐
[EPA AQS API]     ──► ingest_air.py    ──► data/processed/air.csv    ──┤
[FBI CDE API]     ──► ingest_crime.py  ──► data/processed/crime.csv  ──┘
                                                                        │
                                                          joined on FIPS in Power BI
                                                                        │
                                                                        ▼
                                                          Power BI Dashboard (3 pages)
                                                          ├── Demographics
                                                          ├── Air Quality
                                                          └── Crime
```

All sources are keyed on **5-digit county FIPS code** (2-digit state + 3-digit county).
No name-based joins are used — county names are inconsistent and duplicated across states.
The three CSVs are loaded as separate tables in Power BI and linked via the FIPS key in
the data model. Heavy transformation logic stays in Python; Power BI handles only the join
and presentation layer.

---

## Data Sources

| Source | Granularity | FIPS mapping |
|--------|-------------|--------------|
| **U.S. Census ACS 5-year** | Native county FIPS | Direct — the API returns `state` + `county` fields |
| **EPA AQS (Air Quality)** | Monitor-level annual summaries | Averaged across all monitors in the county |
| **FBI Crime Data Explorer** | Police agency (ORI) | Mapped via FBI's agency crosswalk to county FIPS — see data-quality notes |

### Census ACS variables (ACS 5-year, 2022 vintage)

| Output column | ACS variable(s) | Notes |
|---|---|---|
| `population` | B01003_001E | Total population |
| `median_age` | B01002_001E | Median age (years) |
| `median_household_income` | B19013_001E | Dollars |
| `pct_bachelors_plus` | B15003_022–025E / B15003_001E | % population 25+ with bachelor's or higher |
| `pct_owner_occupied` | B25003_002E / B25003_001E | % occupied units that are owner-occupied |
| `median_home_value` | B25077_001E | Dollars |
| `poverty_rate` | B17001_002E / B17001_001E | % population below poverty line |
| `unemployment_rate` | B23025_005E / B23025_003E | % civilian labor force unemployed |

### EPA AQS variables (annual summary, 2022)

| Output column | Meaning |
|---|---|
| `pm25_annual_mean` | Average PM2.5 concentration across all monitors in the county (μg/m³) |
| `pm25_pct_of_standard` | Annual mean as % of the EPA 2024 limit (9 μg/m³) — >100% exceeds the standard |
| `pm25_exceedance_days` | Number of days in the year that exceeded the standard |
| `pm25_98th_percentile` | Typical bad day — filters out one-off wildfire spikes |
| `pm25_worst_day` | Single worst reading of the year (μg/m³) |
| `pm25_std_dev` | Variability — high std dev means occasional severe spikes (e.g. wildfire counties) |
| `pm25_monitor_count` | Number of monitors — counties with 0 have no PM2.5 data |
| Same columns for `ozone_*` | Ozone standard: 0.070 ppm (EPA 8-hour standard) |

---

## Data Quality & Known Limitations

### Census ACS margins of error
ACS 5-year estimates carry margins of error, especially for small counties.
The pipeline pulls point estimates only. For counties with population < 10,000,
treat derived rates with caution.

### EPA air quality monitor coverage
AQS monitors are unevenly distributed — rural counties often have none. Counties
with no monitor appear as `NaN` in air.csv (not dropped). The `pm25_monitor_count`
column makes coverage gaps explicit. The EPA annual standard (9 μg/m³) is used as
the reference; the WHO guideline is stricter at 5 μg/m³.

### FBI crime coverage gaps
The FBI Crime Data Explorer collects data voluntarily from state and local agencies.
Coverage is **incomplete**: not all agencies report, some report partial years,
and data is keyed to police jurisdiction (ORI), not county.
- The pipeline documents which counties have **no agency data**, which have
  **partial coverage**, and which appear **fully covered**.
- Missing counties are **flagged** rather than silently dropped.

---

## Running the Pipeline

All three data sources publish annual updates. Run the pipeline once per year
when new vintages are released (Census ACS in December, EPA AQS mid-year, FBI annually).
Update `ACS_YEAR` in `src/config.py` to match the new vintage before running.

```bash
# 1. Clone and set up environment
git clone <repo-url>
cd county-relocation-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Add API keys (all free-tier — see .env.example for signup links)
cp .env.example .env
# Edit .env with your keys

# 3. Run each ingest module
python3 src/ingest_census.py    # → data/processed/census.csv  (~3,200 counties)
python3 src/ingest_air.py       # → data/processed/air.csv     (~1,500 counties with monitors)
python3 src/ingest_crime.py     # → data/processed/crime.csv   (coverage varies)

# 4. Load the three CSVs into Power BI and link on the fips column
```

---

## Build Status

| Phase | Status |
|-------|--------|
| Phase 1 — Repo scaffold + Census ingest (single state) | ✅ Complete |
| Phase 2 — Census all states + EPA air quality | ✅ Complete |
| Phase 3 — FBI crime ingest + gap handling | ⬜ In progress |
| Power BI dashboard | ⬜ Pending |
