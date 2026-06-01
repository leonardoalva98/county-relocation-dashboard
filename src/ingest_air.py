"""
Ingest EPA AQS annual air quality data for all U.S. counties.

Uses the annualData endpoint — the EPA pre-aggregates to one row per monitor
per year, so we get ~1,600 rows for California vs 100k+ from dailyData.

Saves each state incrementally so progress is never lost if the run is interrupted.
Resume by re-running — already-saved state files are skipped automatically.

Output: data/processed/air.csv  (join key: fips)
"""
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AQS_YEAR, PROCESSED_DIR, RAW_DIR, US_STATE_FIPS, make_fips

load_dotenv()

EPA_BASE_URL  = "https://aqs.epa.gov/data/api"
REQUEST_DELAY = 0.5

PM25_ANNUAL_STANDARD = 9.0    # μg/m³
OZONE_8HR_STANDARD   = 0.070  # ppm

PM25_STANDARD_LABEL  = "PM25 Annual 2024"
OZONE_STANDARD_LABEL = "Ozone 8-hour 2015"

POLLUTANTS = {
    "88101": ("pm25",  PM25_ANNUAL_STANDARD,  PM25_STANDARD_LABEL),
    "44201": ("ozone", OZONE_8HR_STANDARD,    OZONE_STANDARD_LABEL),
}

KEEP_COLS = [
    "state_code", "county_code",
    "validity_indicator", "pollutant_standard",
    "arithmetic_mean", "standard_deviation",
    "primary_exceedance_count",
    "ninety_eighth_percentile",
    "first_max_value",
    "observation_count", "valid_day_count", "required_day_count",
]


def state_cache_path(label: str, state_fips: str) -> Path:
    return RAW_DIR / f"air_{label}_{AQS_YEAR}_state{state_fips}.json"


def fetch_annual_by_state(state_fips: str, param_code: str, email: str, key: str) -> list[dict]:
    url = f"{EPA_BASE_URL}/annualData/byState"
    params = {
        "email": email,
        "key":   key,
        "param": param_code,
        "bdate": f"{AQS_YEAR}0101",
        "edate": f"{AQS_YEAR}1231",
        "state": state_fips,
    }
    resp = requests.get(url, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json().get("Data", [])


def clean_and_aggregate(df: pd.DataFrame, col: str, standard_val: float, standard_label: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    available = [c for c in KEEP_COLS if c in df.columns]
    df = df[available].copy()
    df = df[df["validity_indicator"] == "Y"]

    if "pollutant_standard" in df.columns:
        df = df[df["pollutant_standard"] == standard_label]

    df = df.drop(columns=["validity_indicator", "pollutant_standard"], errors="ignore")

    for c in df.columns:
        if c not in ("state_code", "county_code"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["fips"] = df.apply(
        lambda r: make_fips(str(r["state_code"]).split(".")[0], str(r["county_code"]).split(".")[0]), axis=1
    )

    agg = (
        df.groupby("fips")
        .agg(
            **{
                f"{col}_annual_mean":     ("arithmetic_mean",         "mean"),
                f"{col}_std_dev":         ("standard_deviation",      "mean"),
                f"{col}_exceedance_days": ("primary_exceedance_count","sum"),
                f"{col}_98th_percentile": ("ninety_eighth_percentile","mean"),
                f"{col}_worst_day":       ("first_max_value",         "max"),
                f"{col}_monitor_count":   ("arithmetic_mean",         "count"),
            }
        )
        .reset_index()
    )

    agg[f"{col}_annual_mean"]     = agg[f"{col}_annual_mean"].round(4)
    agg[f"{col}_std_dev"]         = agg[f"{col}_std_dev"].round(4)
    agg[f"{col}_98th_percentile"] = agg[f"{col}_98th_percentile"].round(4)
    agg[f"{col}_worst_day"]       = agg[f"{col}_worst_day"].round(4)
    agg[f"{col}_pct_of_standard"] = (agg[f"{col}_annual_mean"] / standard_val * 100).round(1)

    return agg


def run(state_fips: str = "*") -> pd.DataFrame:
    email = os.getenv("EPA_AQS_EMAIL", "")
    key   = os.getenv("EPA_AQS_KEY", "")
    if not email or not key or "example" in email:
        raise EnvironmentError(
            "EPA_AQS_EMAIL and EPA_AQS_KEY are not configured in .env.\n"
            "Register at: https://aqs.epa.gov/aqsweb/documents/data_api.html#signup"
        )

    states = US_STATE_FIPS if state_fips == "*" else [state_fips]
    county_frames: list[pd.DataFrame] = []

    for param_code, (label, standard_val, standard_label) in POLLUTANTS.items():
        total   = len(states)
        fetched = 0
        skipped = 0

        print(f"\n{'='*60}")
        print(f"  {label.upper()}  |  {total} states  |  year={AQS_YEAR}")
        print(f"{'='*60}")

        for i, s in enumerate(states, 1):
            cache = state_cache_path(label, s)

            if cache.exists():
                skipped += 1
                print(f"  [{i:02d}/{total}] state={s}  CACHED ✓")
                continue

            start = time.time()
            try:
                records = fetch_annual_by_state(s, param_code, email, key)
            except Exception as e:
                print(f"  [{i:02d}/{total}] state={s}  ERROR: {e}")
                continue

            elapsed = time.time() - start
            pd.DataFrame(records).to_json(cache, orient="records")
            fetched += 1
            print(f"  [{i:02d}/{total}] state={s}  {len(records):>5} records  ({elapsed:.1f}s)", flush=True)
            time.sleep(REQUEST_DELAY)

        print(f"\n  Done — {fetched} fetched, {skipped} from cache")

        # Combine all per-state cache files
        all_frames = []
        for s in states:
            cache = state_cache_path(label, s)
            if cache.exists():
                df = pd.read_json(cache)
                if not df.empty:
                    all_frames.append(df)

        raw_df = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
        print(f"  Total raw records: {len(raw_df):,}")

        agg = clean_and_aggregate(raw_df, label, standard_val, standard_label)
        county_frames.append(agg)

    merged = county_frames[0]
    for frame in county_frames[1:]:
        merged = merged.merge(frame, on="fips", how="outer")

    merged = merged.sort_values("fips").reset_index(drop=True)

    out_path = PROCESSED_DIR / "air.csv"
    merged.to_csv(out_path, index=False)

    print(f"\nAir quality → {out_path}  ({len(merged):,} counties with monitor data)")

    return merged


if __name__ == "__main__":
    run()
