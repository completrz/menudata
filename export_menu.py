import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ====== EDIT THESE ONLY IF YOU WANT ======
TAB_NAME = os.environ.get("TAB_NAME", "Menu")  # your sheet tab name
OUT_DIR = Path(os.environ.get("OUT_DIR", ".")).resolve()
# ========================================

SHEET_ID = os.environ.get("SHEET_ID", "").strip()         # set via GitHub Secret
CREDS_PATH = os.environ.get("GOOGLE_CREDS", "service_account.json")  # created by workflow

SNAP_DIR = OUT_DIR / "snapshots"
LATEST_PATH = OUT_DIR / "latest.json"

REQUIRED_HEADERS = ["category", "item", "price", "description", "available", "sort", "image_url"]

def stable_hash(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()

def norm_bool(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s == "":
        return default
    return s in ("true", "1", "yes", "y", "t")

def norm_sort(v, default=0.0) -> float:
    try:
        s = str(v).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default

def read_sheet_rows():
    if not SHEET_ID:
        raise RuntimeError("Missing SHEET_ID (set it as env var / GitHub secret).")

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB_NAME)

    # get_all_records() expects headers in row 1
    rows = ws.get_all_records()
    return rows

def validate_headers(rows):
    # get_all_records loses header row; so we validate by checking keys present in first row (if any)
    if not rows:
        return
    keys = set(rows[0].keys())
    missing = [h for h in REQUIRED_HEADERS if h not in keys]
    if missing:
        raise RuntimeError(
            f"Your sheet is missing columns: {missing}\n"
            f"Expected headers: {REQUIRED_HEADERS}"
        )

def build_menu(rows):
    validate_headers(rows)

    items = []
    for r in rows:
        category = str(r.get("category", "")).strip()
        name = str(r.get("item", "")).strip()
        if not category or not name:
            continue

        if not norm_bool(r.get("available", True), default=True):
            continue

        price_raw = r.get("price", "")
        price_display = str(price_raw).strip()

        items.append({
            "category": category,
            "name": name,
            "description": str(r.get("description", "")).strip(),
            "price_display": price_display,
            "image_url": str(r.get("image_url", "")).strip(),
            "sort": norm_sort(r.get("sort", 0), default=0),
        })

    # Group by category
    grouped = {}
    for it in items:
        grouped.setdefault(it["category"], []).append(it)

    categories = []
    for cat_name, cat_items in grouped.items():
        cat_items.sort(key=lambda x: (x["sort"], x["name"].lower()))
        categories.append({
            "name": cat_name,
            "sort": min((x["sort"] for x in cat_items), default=0),
            "items": [
                {
                    "name": x["name"],
                    "description": x["description"],
                    "price_display": x["price_display"],
                    "image_url": x["image_url"],
                }
                for x in cat_items
            ]
        })

    categories.sort(key=lambda c: (c["sort"], c["name"].lower()))

    now = datetime.now(timezone.utc).isoformat()
    menu = {"generated_at": now, "categories": categories}
    menu["hash"] = stable_hash(menu)
    return menu

def load_existing_hash():
    if not LATEST_PATH.exists():
        return None
    try:
        with open(LATEST_PATH, "r", encoding="utf-8") as f:
            old = json.load(f)
        return old.get("hash")
    except Exception:
        return None

def write_outputs(menu):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    old_hash = load_existing_hash()
    if old_hash == menu["hash"]:
        print("No change. (latest.json unchanged)")
        return False

    with open(LATEST_PATH, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    snap_path = SNAP_DIR / f"{ts}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump(menu, f, ensure_ascii=False, indent=2)

    print("Wrote latest.json and snapshot:", snap_path)
    return True

def main():
    rows = read_sheet_rows()
    menu = build_menu(rows)
    write_outputs(menu)

if __name__ == "__main__":
    main()
