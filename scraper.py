#!/usr/bin/env python3
"""
eauction24.gr scraper -> data/auctions.json (+ new-listings diff)
Parses schema.org RealEstateListing JSON-LD from each auction detail page.
Public judicial-auction data (same records published on eauction.gr).
"""
import json, re, time, sys, os, urllib.parse, datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://eauction24.gr"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DATA = Path("data"); DATA.mkdir(exist_ok=True)
STORE = DATA / "auctions.json"

# 13 Greek administrative regions (Greek names as used by the site)
REGIONS = [
    "Αττικής", "Κεντρικής Μακεδονίας", "Θεσσαλίας", "Πελοποννήσου",
    "Δυτικής Ελλάδας", "Κρήτης", "Στερεάς Ελλάδας", "Ηπείρου",
    "Ανατολικής Μακεδονίας και Θράκης", "Δυτικής Μακεδονίας",
    "Ιονίων Νήσων", "Βορείου Αιγαίου", "Νοτίου Αιγαίου",
]

def classify(type_str, name):
    t = (type_str or "").lower(); n = (name or "").lower()
    if any(k in t for k in ["land", "parcel"]) or any(k in n for k in ["οικόπεδο", "αγρόκτημα", "αγροτεμάχιο", "γήπεδο", "κληροτεμάχιο"]):
        return "Land"
    if any(k in t for k in ["store", "office", "commercial"]) or any(k in n for k in ["κατάστημα", "επαγγελματ", "γραφείο", "βιοτεχν", "αποθήκη", "ξενοδοχ"]):
        return "Commercial"
    if any(k in t for k in ["residence", "house", "apartment"]) or any(k in n for k in ["κατοικία", "διαμέρισμα", "μονοκατοικία", "μεζονέτα"]):
        return "Residential"
    return "Other"

def get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 * (i + 1))
    return None

def ids_in_region(region, max_pages=40):
    slug = urllib.parse.quote(region)
    ids, page = set(), 1
    while page <= max_pages:
        html = get(f"{BASE}/auctions/{slug}?page={page}")
        if not html:
            break
        found = set(re.findall(r"/auction/(\d+)", html))
        new = found - ids
        if not new:
            return ids  # empty page -> reached the natural end
        ids |= found
        page += 1
        time.sleep(0.6)
    print(f"  WARNING [{region}] hit MAX_PAGES={max_pages} without an empty page — "
          f"results are truncated, raise MAX_PAGES", file=sys.stderr)
    return ids

def parse_detail(aid):
    html = get(f"{BASE}/auction/{aid}")
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(s.string)
        except Exception:
            continue
        if d.get("@type") != "RealEstateListing":
            continue
        me = d.get("mainEntity", {}) or {}
        addr = me.get("address", {}) or {}
        off = d.get("offers", {}) or {}
        fs = me.get("floorSize", {}) or {}
        return {
            "id": int(d.get("identifier", aid)),
            "url": d.get("url", f"{BASE}/auction/{aid}"),
            "title": d.get("name"),
            "type": classify(me.get("@type"), d.get("name")),
            "raw_type": me.get("@type"),
            "area_m2": fs.get("value"),
            "price_eur": off.get("price"),
            "auction_date": off.get("availabilityStarts") or d.get("datePosted"),
            "region": addr.get("addressRegion"),
            "municipality": addr.get("addressLocality"),
            "address": addr.get("streetAddress"),
            "bedrooms": me.get("numberOfBedrooms"),
            "image": (d.get("image") or [None])[0],
            "description": (d.get("description") or "")[:400],
        }
    return None

def main():
    regions = sys.argv[1:] or REGIONS
    scanned = set(regions)
    max_pages = int(os.environ.get("MAX_PAGES", "40"))
    prev = {}
    if STORE.exists():
        prev = {r["id"]: r for r in json.loads(STORE.read_text())}
    today = datetime.date.today().isoformat()

    all_ids = set()
    for reg in regions:
        got = ids_in_region(reg, max_pages)
        print(f"[{reg}] {len(got)} listings", file=sys.stderr)
        all_ids |= got

    # start from full history so delisted lots aren't lost (drop_tracker.py
    # needs past rounds to link re-auctions, which get a new id each round)
    records = dict(prev)
    new_ids = []
    for i, aid in enumerate(sorted(all_ids, key=int), 1):
        aid_i = int(aid)
        if aid_i in prev:                       # already known: reuse, keep first_seen
            rec = dict(prev[aid_i])
            rec["status"] = "active"
            rec["last_seen"] = today
        else:
            rec = parse_detail(aid)
            if not rec:
                continue
            rec["first_seen"] = today
            rec["last_seen"] = today
            rec["status"] = "active"
            new_ids.append(aid_i)
            time.sleep(0.5)
        records[aid_i] = rec
        if i % 25 == 0:
            print(f"  ...{i}/{len(all_ids)}", file=sys.stderr)

    # anything previously active in a region we actually scanned this run,
    # but no longer listed -> delisted (sold, cancelled, or pending re-auction).
    # regions NOT scanned this run (subset test runs) are left untouched.
    for aid_i, rec in prev.items():
        if aid_i in all_ids or rec.get("region") not in scanned or rec.get("status") == "removed":
            continue
        rec = dict(rec)
        rec["status"] = "removed"
        rec["removed_seen"] = today
        records[aid_i] = rec

    out = sorted(records.values(), key=lambda r: (r.get("first_seen") or "", r["id"]), reverse=True)
    STORE.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    active = sum(1 for r in out if r.get("status", "active") == "active")
    (DATA / "meta.json").write_text(json.dumps({
        "last_run": datetime.datetime.now().isoformat(timespec="seconds"),
        "total": len(out), "active": active, "new_today": len(new_ids), "new_ids": new_ids,
    }, ensure_ascii=False, indent=1))
    print(f"TOTAL {len(out)} | ACTIVE {active} | NEW {len(new_ids)}", file=sys.stderr)

if __name__ == "__main__":
    main()
