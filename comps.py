#!/usr/bin/env python3
"""
Scores each active listing's price-per-m2 against a local baseline, so a
low price can be told apart from a low price *for that area* -- the
"discount score" from ROADMAP.md's Phase 1 remainder.

Median euro/m2 is computed per (region, municipality) among active,
priced, sized listings. A municipality needs at least MIN_SAMPLE
comparable listings to get its own median; below that, falls back to the
region-wide median (still gated by MIN_SAMPLE), and the "basis"/
"sample_size" fields say which one was used and how thin it is -- a
comp built from 3 listings is a much weaker signal than one from 40.

Two real quirks verified against live data, both of which silently wreck
a naive per-area median if left in:

1. Partial/undivided ownership shares (e.g. a 1/8 inheritance share)
   auctioned at a nominal price disconnected from the property's real
   value -- e.g. a 65.71 m2 house listed at EUR 1. Guarded with IQR
   trimming (excludes values outside Q1-1.5*IQR..Q3+1.5*IQR) when the
   group is large enough for quartiles to mean anything; listings below
   that bound still get scored, just marked "low_price_outlier".

2. The SAME physical parcel auctioned repeatedly as separate fractional
   shares -- verified live: one municipality had 10 land listings all
   priced 25,500 m2, priced from EUR 500 to EUR 22,000 each. That's not
   10 comparable data points, it's fragments of one parcel; left alone
   they dominate and collapse that municipality's median toward zero.

   Tried matching on drop_tracker.py's normalized-address grouping first
   -- it under-matched here because the free-text address field has Greek
   case-declension variance ("Δήμος" vs "Δήμου", "Περιφέρεια" vs
   "Περιφέρειας") and reordered phrasing across what's otherwise the same
   location. The site's listing *title*, though, is template-generated
   ("{type} {area} τ.μ. {municipality} σε πλειστηριασμό") and matches
   exactly across fragments, so clustering key here is
   (region, municipality, type, area_m2) instead -- coarser than an
   address match, but reliable for this specific purpose: catching
   non-independent duplicates before they skew a statistical baseline.
   Clusters of 2+ active listings get only their single highest
   price_per_m2 counted toward the baseline, and every member is marked
   "shared_listing" so the dashboard can flag it for extra scrutiny.
"""
import json, statistics, sys
from pathlib import Path

DATA = Path("data")
STORE = DATA / "auctions.json"
OUT = DATA / "comps.json"
# below this, a group is too small for either quartiles or a median to be
# trustworthy -- verified live: a 3-sample municipality median got dragged
# to near-zero by a single nominal-price listing, with no trim to catch it
MIN_SAMPLE = 5


def ppsqm(r):
    if r.get("price_eur") and r.get("area_m2"):
        return r["price_eur"] / r["area_m2"]
    return None


def trimmed(values):
    """(clean_values, lower_bound, upper_bound) -- values is always >= MIN_SAMPLE here."""
    q1, _, q3 = statistics.quantiles(values, n=4)
    lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    clean = [v for v in values if lo <= v <= hi]
    return (clean if len(clean) >= MIN_SAMPLE else values), lo, hi


def main():
    if not STORE.exists():
        print("no data/auctions.json yet; run scraper.py first", file=sys.stderr)
        return

    records = [r for r in json.loads(STORE.read_text()) if r.get("status", "active") == "active"]

    # cluster active listings sharing region+municipality+type+area, to catch
    # the same parcel auctioned repeatedly as separate fractional shares
    clusters = {}
    for r in records:
        if r.get("area_m2") is None:
            continue
        clusters.setdefault((r.get("region"), r.get("municipality"), r.get("type"), r.get("area_m2")), []).append(r)

    shared_ids = set()
    baseline_ppsqm = {}  # id -> ppsqm contributed to the baseline pool (deduped per cluster)
    for rows in clusters.values():
        if len(rows) < 2:
            continue
        priced = [(r, ppsqm(r)) for r in rows]
        priced = [(r, p) for r, p in priced if p is not None]
        if len(priced) < 2:
            continue
        shared_ids.update(r["id"] for r, _ in priced)
        best = max(priced, key=lambda rp: rp[1])
        baseline_ppsqm[best[0]["id"]] = best[1]

    by_muni, by_region = {}, {}
    for r in records:
        p = ppsqm(r)
        if p is None:
            continue
        if r["id"] in shared_ids and r["id"] not in baseline_ppsqm:
            continue  # this cluster's representative value already counted
        p = baseline_ppsqm.get(r["id"], p)
        by_region.setdefault(r.get("region"), []).append(p)
        by_muni.setdefault((r.get("region"), r.get("municipality")), []).append(p)

    muni_stats, region_stats = {}, {}
    for k, v in by_muni.items():
        if len(v) >= MIN_SAMPLE:
            clean, lo, hi = trimmed(v)
            muni_stats[k] = (statistics.median(clean), lo, hi)
    for k, v in by_region.items():
        if len(v) >= MIN_SAMPLE:
            clean, lo, hi = trimmed(v)
            region_stats[k] = (statistics.median(clean), lo, hi)

    comps = {}
    for r in records:
        p = ppsqm(r)
        if p is None:
            continue
        key = (r.get("region"), r.get("municipality"))
        stat, basis, sample = muni_stats.get(key), "municipality", len(by_muni.get(key, []))
        if stat is None:
            stat = region_stats.get(r.get("region"))
            basis, sample = "region", len(by_region.get(r.get("region"), []))
        if stat is None:
            continue
        median, lower_bound, upper_bound = stat
        comps[r["id"]] = {
            "ppsqm": round(p),
            "low_price_outlier": lower_bound is not None and p < lower_bound,
            "high_price_outlier": upper_bound is not None and p > upper_bound,
            "shared_listing": r["id"] in shared_ids,
            "median_ppsqm": round(median),
            "vs_median_pct": round(100 * (p - median) / median, 1),
            "basis": basis,
            "sample_size": sample,
        }

    OUT.write_text(json.dumps(comps, ensure_ascii=False, indent=1))
    below = sum(1 for c in comps.values() if c["vs_median_pct"] <= -10 and not c["low_price_outlier"] and not c["shared_listing"])
    lo_out = sum(1 for c in comps.values() if c["low_price_outlier"])
    hi_out = sum(1 for c in comps.values() if c["high_price_outlier"])
    shared = sum(1 for c in comps.values() if c["shared_listing"])
    print(f"COMPS {len(comps)} listings scored | {below} priced 10%+ below local median | "
          f"{lo_out} low-price outliers | {hi_out} high-price outliers | {shared} shared/fractional listings flagged",
          file=sys.stderr)


if __name__ == "__main__":
    main()
