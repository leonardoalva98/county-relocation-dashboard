"""
Ingest FBI Crime Data Explorer violent and property crime rates at the city level.

Approach:
  1. Fetch all city-type agencies for each state
  2. For each agency fetch violent-crime and property-crime annual rates
  3. Parse city name from agency name
  4. Match to Census place_fips via city name + state normalization
  5. Flag cities with no data rather than dropping them

Saves each agency incrementally — re-running skips already-fetched agencies.

Output: data/processed/crime.csv  (join key: place_fips)
"""
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import PROCESSED_DIR, RAW_DIR

load_dotenv()

FBI_BASE     = "https://api.usa.gov/crime/fbi/cde"
CRIME_YEAR   = 2025
REQUEST_DELAY = 0.5

OFFENSE_TYPES = ["violent-crime", "property-crime"]

# State abbreviation → FIPS (for joining back to Census state_name)
STATE_ABBR_TO_NAME = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California",
    "CO":"Colorado","CT":"Connecticut","DE":"Delaware","DC":"District of Columbia",
    "FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois",
    "IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky","LA":"Louisiana",
    "ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota",
    "MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada",
    "NH":"New Hampshire","NJ":"New Jersey","NM":"New Mexico","NY":"New York",
    "NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma",
    "OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont",
    "VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming",
}

# Suffixes to strip — "City Police Department" must come before "Police Department"
# so cities named "X City" keep their "City" suffix
_SUFFIXES = re.compile(
    r"\s+(city police department|city police dept\.?|"
    r"police department|police dept\.?|department of police|"
    r"police dept|police|dept\.?|pd)$",
    re.IGNORECASE,
)
_PREFIX = re.compile(r"^(city of|town of|village of|borough of)\s+", re.IGNORECASE)

# Manual overrides for FBI names that don't match Census official names
CITY_OVERRIDES = {
    "Ventura":               "San Buenaventura (Ventura)",
    "Paso Robles":           "El Paso de Robles (Paso Robles)",
    "Carmel":                "Carmel-by-the-Sea",
    "La Canada Flintridge":  "La Cañada Flintridge",
    "Bear Valley":           None,   # ambiguous — two Census places with this name
    "Central Marin":         None,   # regional department, not a Census place
}


def extract_city(agency_name: str) -> str:
    name = _PREFIX.sub("", agency_name)
    name = _SUFFIXES.sub("", name)
    name = name.strip().rstrip(",").strip()
    return CITY_OVERRIDES.get(name, name)  # apply override if one exists


def normalize(s) -> str | None:
    if not s or not isinstance(s, str):
        return None
    s = re.sub(r"\b(city|town|village|borough|cdp)\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip().lower()


def agency_cache_path(ori: str) -> Path:
    return RAW_DIR / f"crime_{CRIME_YEAR}_{ori}.json"


def fetch_agencies(state_abbr: str, api_key: str) -> list[dict]:
    cache = RAW_DIR / f"crime_agencies_{state_abbr}.json"
    if cache.exists():
        return pd.read_json(cache).to_dict(orient="records")
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{FBI_BASE}/agency/byStateAbbr/{state_abbr}",
                params={"API_KEY": api_key}, timeout=120,
            )
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"  WARNING: could not fetch agencies for {state_abbr}: {e}")
                return []
            time.sleep(5)
    data     = resp.json()
    agencies = [a for county in data.values() for a in county
                if a.get("agency_type_name") == "City"]
    pd.DataFrame(agencies).to_json(cache, orient="records")
    return agencies


def fetch_offense(ori: str, offense: str, api_key: str) -> dict:
    for attempt in range(3):
        try:
            resp = requests.get(
                f"{FBI_BASE}/summarized/agency/{ori}/{offense}",
                params={
                    "from": f"01-{CRIME_YEAR}",
                    "to":   f"12-{CRIME_YEAR}",
                    "API_KEY": api_key,
                },
                timeout=120,
            )
            if resp.status_code != 200:
                return {}
            return resp.json()
        except Exception:
            if attempt == 2:
                return {}
            time.sleep(5)


def annual_rate(data: dict, agency_name: str) -> float | None:
    rates = data.get("offenses", {}).get("rates", {})
    key   = f"{agency_name} Offenses"
    if key not in rates:
        return None
    monthly = [v for v in rates[key].values() if v is not None]
    return round(sum(monthly) / len(monthly), 2) if monthly else None


def annual_count(data: dict, agency_name: str) -> int | None:
    actuals = data.get("offenses", {}).get("actuals", {})
    key     = f"{agency_name} Offenses"
    if key not in actuals:
        return None
    monthly = [v for v in actuals[key].values() if v is not None]
    return sum(monthly) if monthly else None


def run(state_abbrs: list[str] | None = None) -> pd.DataFrame:
    api_key = os.getenv("FBI_API_KEY", "")
    if not api_key or api_key == "your_fbi_api_key_here":
        raise EnvironmentError("FBI_API_KEY not set in .env")

    if state_abbrs is None:
        state_abbrs = list(STATE_ABBR_TO_NAME.keys())  # all 50 states + DC

    all_rows: list[dict] = []

    for state_abbr in state_abbrs:
        state_name = STATE_ABBR_TO_NAME.get(state_abbr, state_abbr)
        print(f"\n{'='*60}")
        print(f"  {state_abbr} — {state_name}")
        print(f"{'='*60}")

        agencies = fetch_agencies(state_abbr, api_key)
        print(f"  City agencies: {len(agencies)}")

        for i, agency in enumerate(agencies, 1):
            ori         = agency["ori"]
            agency_name = agency["agency_name"]
            cache       = agency_cache_path(ori)

            if cache.exists():
                row = pd.read_json(cache, typ="series").to_dict()
                row["city_parsed"] = extract_city(agency_name)  # always recompute
                all_rows.append(row)
                print(f"  [{i:03d}/{len(agencies)}] CACHED  {agency_name}", flush=True)
                continue

            result = {
                "ori":          ori,
                "agency_name":  agency_name,
                "city_parsed":  extract_city(agency_name),
                "state_abbr":   state_abbr,
                "state_name":   state_name,
                "population":   None,
                "violent_crime_rate":   None,
                "property_crime_rate":  None,
                "violent_crime_count":  None,
                "property_crime_count": None,
                "data_available": False,
            }

            for offense in OFFENSE_TYPES:
                data = fetch_offense(ori, offense, api_key)
                time.sleep(REQUEST_DELAY)

                if not data:
                    continue

                # population
                pop_data = data.get("populations", {}).get("population", {}).get(agency_name, {})
                if pop_data:
                    result["population"] = list(pop_data.values())[0]

                rate  = annual_rate(data, agency_name)
                count = annual_count(data, agency_name)

                if offense == "violent-crime":
                    result["violent_crime_rate"]  = rate
                    result["violent_crime_count"] = count
                else:
                    result["property_crime_rate"]  = rate
                    result["property_crime_count"] = count

                if rate is not None:
                    result["data_available"] = True

            pd.Series(result).to_json(cache)
            all_rows.append(result)
            status = "OK" if result["data_available"] else "NO DATA"
            print(f"  [{i:03d}/{len(agencies)}] {status:8s}  {agency_name}", flush=True)

    df = pd.DataFrame(all_rows)

    # Match to Census place_fips
    census = pd.read_csv(PROCESSED_DIR / "census.csv", dtype={"place_fips": str})
    census["_norm_place"] = census["place_name"].apply(normalize)
    census["_norm_state"] = census["state_name"].str.lower()

    df["_norm_city"]  = df["city_parsed"].apply(normalize)
    df["_norm_state"] = df["state_name"].str.lower()

    lookup = census.set_index(["_norm_place", "_norm_state"])["place_fips"].to_dict()
    df["place_fips"] = df.apply(
        lambda r: lookup.get((r["_norm_city"], r["_norm_state"])), axis=1
    )

    matched   = df["place_fips"].notna().sum()
    unmatched = df["place_fips"].isna().sum()
    print(f"\n  Census match: {matched} matched, {unmatched} unmatched")

    final_cols = [
        "place_fips", "city_parsed", "state_abbr", "state_name",
        "ori", "agency_name", "population",
        "violent_crime_rate", "property_crime_rate",
        "violent_crime_count", "property_crime_count",
        "data_available",
    ]
    df = df[final_cols].sort_values(["state_abbr", "city_parsed"]).reset_index(drop=True)

    out_path = PROCESSED_DIR / "crime.csv"
    df.to_csv(out_path, index=False)
    print(f"\nCrime → {out_path}  ({len(df):,} agencies)")
    print(df.head(15).to_string())

    return df


if __name__ == "__main__":
    run()
