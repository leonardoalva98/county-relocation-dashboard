"""
Ingest U.S. Census ACS 5-year data at the city/place level.

Geography: Census 'place' (incorporated cities, towns, census-designated places).
~30,000 places across all states. Join key: 7-digit place_fips (2-digit state + 5-digit place code).

Output: data/processed/census.csv
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ACS_BASE_URL, PROCESSED_DIR, RAW_DIR, make_place_fips

load_dotenv()

ACS_VARS: list[tuple[str, str]] = [
    ("NAME",          "name"),
    ("B01003_001E",   "population"),
    ("B01002_001E",   "median_age"),
    ("B19013_001E",   "median_household_income"),
    ("B15003_001E",   "edu_total"),
    ("B15003_022E",   "edu_bachelors"),
    ("B15003_023E",   "edu_masters"),
    ("B15003_024E",   "edu_professional"),
    ("B15003_025E",   "edu_doctorate"),
    ("B25003_001E",   "housing_total"),
    ("B25003_002E",   "housing_owner_occupied"),
    ("B25077_001E",   "median_home_value"),
    ("B17001_001E",   "poverty_universe"),
    ("B17001_002E",   "poverty_below"),
    ("B23025_003E",   "labor_force"),
    ("B23025_005E",   "unemployed"),
]

CENSUS_SENTINELS = {-666666666, -999999999, -888888888, -222222222, -333333333}


def fetch_raw(state_fips: str, api_key: str) -> list[list]:
    variable_names = ",".join(v for v, _ in ACS_VARS)
    params = {
        "get": variable_names,
        "for": "place:*",
        "in":  f"state:{state_fips}",
        "key": api_key,
    }
    resp = requests.get(ACS_BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def save_raw(data: list[list], state_fips: str) -> Path:
    label    = "all_states" if state_fips == "*" else f"state{state_fips}"
    out_path = RAW_DIR / f"census_raw_{label}.json"
    out_path.write_text(json.dumps(data, indent=2))
    print(f"  Raw saved → {out_path}")
    return out_path


def clean(raw: list[list]) -> pd.DataFrame:
    headers = raw[0]
    rows    = raw[1:]
    df      = pd.DataFrame(rows, columns=headers)

    api_to_label = {api: label for api, label in ACS_VARS if api != "NAME"}
    df = df.rename(columns=api_to_label)

    # 7-digit place FIPS key
    df["place_fips"] = df.apply(lambda r: make_place_fips(r["state"], r["place"]), axis=1)

    # Parse place name and state from "Los Angeles city, California"
    name_parts      = df["NAME"].str.rsplit(",", n=1, expand=True)
    df["place_name"] = name_parts[0].str.strip()
    df["state_name"] = name_parts[1].str.strip()

    # Numeric coercion + sentinel replacement
    numeric_cols = [label for api, label in ACS_VARS if api != "NAME"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].where(~df[col].isin(CENSUS_SENTINELS))

    # Derived rates
    df["pct_bachelors_plus"] = (
        (df["edu_bachelors"] + df["edu_masters"] + df["edu_professional"] + df["edu_doctorate"])
        / df["edu_total"] * 100
    ).round(2)

    df["pct_owner_occupied"] = (
        df["housing_owner_occupied"] / df["housing_total"] * 100
    ).round(2)

    df["poverty_rate"] = (
        df["poverty_below"] / df["poverty_universe"] * 100
    ).round(2)

    df["unemployment_rate"] = (
        df["unemployed"] / df["labor_force"] * 100
    ).round(2)

    final_cols = [
        "place_fips",
        "place_name",
        "state_name",
        "population",
        "median_age",
        "median_household_income",
        "pct_bachelors_plus",
        "pct_owner_occupied",
        "median_home_value",
        "poverty_rate",
        "unemployment_rate",
    ]
    return df[final_cols].sort_values("place_fips").reset_index(drop=True)


def run(state_fips: str = "*") -> pd.DataFrame:
    api_key = os.getenv("CENSUS_API_KEY")
    if not api_key:
        raise EnvironmentError("CENSUS_API_KEY is not set. Copy .env.example → .env and add your key.")

    print(f"Fetching ACS 5-year place-level data  state={state_fips!r} ...")
    raw = fetch_raw(state_fips, api_key)
    save_raw(raw, state_fips)

    print("Cleaning ...")
    df = clean(raw)

    out_path = PROCESSED_DIR / "census.csv"
    df.to_csv(out_path, index=False)
    print(f"  Saved → {out_path}  ({len(df):,} places)")

    missing = df.isnull().sum()
    missing = missing[missing > 0]
    if not missing.empty:
        print("\n  Missing value counts:")
        print(missing.to_string())

    return df


if __name__ == "__main__":
    run()
