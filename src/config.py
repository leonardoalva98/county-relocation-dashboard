"""
Shared constants, path helpers, and FIPS utilities used across all ingest modules.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# ── Census ACS ─────────────────────────────────────────────────────────────────
ACS_YEAR = 2024          # latest published ACS 5-year vintage (released Dec 2024)
ACS_BASE_URL = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"

# ── EPA AQS ────────────────────────────────────────────────────────────────────
AQS_YEAR = 2025          # latest available EPA AQS annual data

# All 50 states + DC — used to loop EPA AQS requests (no "*" wildcard on that API)
US_STATE_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12",
    "13", "15", "16", "17", "18", "19", "20", "21", "22", "23",
    "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
    "34", "35", "36", "37", "38", "39", "40", "41", "42", "44",
    "45", "46", "47", "48", "49", "50", "51", "53", "54", "55", "56",
]

# ── FIPS helpers ───────────────────────────────────────────────────────────────
def make_county_fips(state: str, county: str) -> str:
    """Return a zero-padded 5-digit county FIPS code."""
    return f"{state.zfill(2)}{county.zfill(3)}"

def make_place_fips(state: str, place: str) -> str:
    """Return a zero-padded 7-digit place FIPS code (state + Census place code)."""
    return f"{state.zfill(2)}{place.zfill(5)}"

# keep old name as alias so ingest_air.py doesn't break
make_fips = make_county_fips
