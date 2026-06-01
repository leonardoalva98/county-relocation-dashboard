# County Relocation Dashboard

> **Business question:** Which U.S. city is the best fit for me to relocate to?  
> This pipeline integrates demographics, air quality, and crime data from free U.S. federal
> APIs into a Power BI dashboard, letting you compare cities across the dimensions that matter most.

---

## Architecture & Data Flow

```
[Census ACS API]  ──► ingest_census.py ──► data/processed/census.csv ──┐
[FBI CDE API]     ──► ingest_crime.py  ──► data/processed/crime.csv  ──┤── city-level (place_fips)
                                                                        │
[EPA AQS API]     ──► ingest_air.py    ──► data/processed/air.csv    ──┘── county-level (county_fips)
                                                                        │
                                                    loaded into Power BI data model
                                                                        │
                                                                        ▼
                                                          Power BI Dashboard (3 pages)
                                                          ├── Demographics
                                                          ├── Air Quality
                                                          └── Crime
```

**Join keys:**
- Census + Crime → joined on `place_fips` (7-digit: 2-digit state + 5-digit Census place code)
- Air Quality → stands alone on `county_fips` (5-digit county FIPS). City-to-county bridge planned for Stage 2.

Heavy transformation logic stays in Python. Power BI handles presentation only.

---

## Data Sources

| Source | Vintage | Granularity | Key |
|--------|---------|-------------|-----|
| **U.S. Census ACS 5-year** | 2024 | City / Census place | `place_fips` |
| **EPA AQS (Air Quality)** | 2025 | County (monitor aggregated) | `county_fips` |
| **FBI Crime Data Explorer** | 2025 | City police agency | `place_fips` (matched via city name) |

### Census ACS variables (ACS 5-year, 2024 vintage)

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

### EPA AQS variables (annual summary, 2025)

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

### FBI Crime variables (2025)

| Output column | Meaning |
|---|---|
| `violent_crime_rate` | Violent crimes per 100,000 people (annual average of monthly rates) |
| `property_crime_rate` | Property crimes per 100,000 people |
| `violent_crime_count` | Raw annual violent crime count |
| `property_crime_count` | Raw annual property crime count |
| `data_available` | False if the agency did not report data for 2025 |

---

## Data Quality & Known Limitations

### Census ACS margins of error
ACS 5-year estimates carry margins of error, especially for small places.
The pipeline pulls point estimates only. For places with population < 10,000,
treat derived rates with caution.

### EPA air quality monitor coverage
AQS monitors are unevenly distributed — rural counties often have none. Counties
with no monitor appear as `NaN` in air.csv (not dropped). The `pm25_monitor_count`
column makes coverage gaps explicit. The EPA annual standard (9 μg/m³) is used as
the reference; the WHO guideline is stricter at 5 μg/m³.

### FBI crime coverage gaps
The FBI Crime Data Explorer collects data voluntarily from local agencies.
Not all agencies report, and some report partial years. City names are parsed
from agency names (e.g. "Los Angeles Police Department" → "Los Angeles") and
matched to Census places — unmatched agencies are flagged with a null `place_fips`
rather than silently dropped. Very small cities (population < ~1,000) may show
extreme per-100k rates that are statistically unreliable.

---

## Running the Pipeline

All three sources publish annual updates. Run once per year when new vintages drop
(Census ACS in December, EPA AQS mid-year, FBI annually).
Update `ACS_YEAR` and `AQS_YEAR` in `src/config.py` before re-running.

```bash
# 1. Clone and set up environment
git clone https://github.com/leonardoalva98/county-relocation-dashboard
cd county-relocation-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Add API keys (all free-tier — see .env.example for signup links)
cp .env.example .env
# Edit .env with your keys

# 3. Run each ingest module
python3 src/ingest_census.py    # → data/processed/census.csv  (~32,000 cities)
python3 src/ingest_air.py       # → data/processed/air.csv     (~850 counties with monitors)
python3 src/ingest_crime.py     # → data/processed/crime.csv   (~8,000 city agencies)

# 4. Load the three CSVs into Power BI and link census + crime on place_fips
```

---

## Build Status

| Phase | Status |
|-------|--------|
| Phase 1 — Repo scaffold + Census ingest | ✅ Complete |
| Phase 2 — Census all cities + EPA air quality (all counties) | ✅ Complete |
| Phase 3 — FBI crime ingest (all states) | 🔄 Running |
| Power BI dashboard | ⬜ Pending |
