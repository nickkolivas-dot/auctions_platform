#!/usr/bin/env python3
"""
Walk-away price per lot: a "don't bid above this" ceiling, deliberately
SEPARATE from comps.py's discount score.

The discount score answers "is this cheap for the area?". The ceiling
answers a different, harder question: "what is the most I can PAY at the
hammer and still clear my target margin after I've fixed it up, paid the
taxes, and sold it on?". A lot can be a deep discount and still a bad bid
if the renovation and costs eat the spread.

Resale anchor: comps.py's local median euro/m2 is the market value proxy.
Greek judicial starting prices are set by a certified appraiser at
commercial value (εμπορική αξία), so the median starting price per m2 for
an area/type is a defensible stand-in for "what it's worth" -- we only use
it where comps.py judged it trustworthy (a real median, not a bare-
ownership / shared / outlier row). No median -> no ceiling; we do not
invent one.

    V_market = median_ppsqm * area_m2
    V_resale = V_market * RESALE_HAIRCUT          # you rarely realise full appraised value
    R        = RENO_PER_M2 * area_m2              # 0 for Land/Parking (no interior to fix)
    ceiling  = (V_resale*(1-MARGIN) - R - LEGAL_CONTINGENCY) / (1 + TXN_COST_PCT)

TXN_COST_PCT is the purchase-side load (transfer tax 3.09% + notary + fees);
MARGIN is the target profit as a fraction of resale value; LEGAL_CONTINGENCY
is a flat legal/eviction buffer -- occupancy can't be read from public data
(verified: the aggregator text doesn't carry it; it's in the appraisal on
the logged-in site), so this stays a manual, conservative flat buffer rather
than a fabricated per-lot number.

Every assumption is an env var with a sane default, so the two of us can
re-tune the whole model in one place without touching code. Ceilings that
come out <= 0 (costs exceed resale) are emitted as 0.0 with viable=False --
an explicit "do not bid", not a missing value.
"""
import json, os, sys
from pathlib import Path

DATA = Path("data")
STORE = DATA / "auctions.json"
COMPS = DATA / "comps.json"
OUT = DATA / "walkaway.json"

RESALE_HAIRCUT = float(os.environ.get("WALKAWAY_RESALE_HAIRCUT") or 0.90)
MARGIN = float(os.environ.get("WALKAWAY_MARGIN") or 0.25)
RENO_PER_M2 = float(os.environ.get("WALKAWAY_RENO_PER_M2") or 350)
TXN_COST_PCT = float(os.environ.get("WALKAWAY_TXN_COST_PCT") or 0.06)
LEGAL_CONTINGENCY = float(os.environ.get("WALKAWAY_LEGAL_CONTINGENCY") or 3000)

# The ceiling is V = median_ppsqm * area. That value model holds for BUILDINGS
# (an apartment's euro/m2 clusters tightly within an area) but breaks for raw
# LAND: land euro/m2 swings wildly with buildability and parcel size, so a
# municipal median (dominated by small buildable plots) extrapolated over a
# big non-buildable field produces a fantasy number -- verified live, a 9,375
# m2 non-buildable farm came out "worth" EUR 5M off a EUR 611/m2 median. Land
# gets a comps discount score but no ceiling; we do not pretend to price it.
CEILING_TYPES = {"Residential", "Commercial", "Warehouse", "Parking"}
# renovation only bites where there's a finished interior to redo
RENO_TYPES = {"Residential", "Commercial"}


def usable_comp(c):
    """A comp is a trustworthy resale anchor only if it carries a real median
    that comps.py did not disqualify. Mirrors comps.py's own exclusions."""
    return bool(
        c
        and c.get("median_ppsqm")
        and not c.get("bare_or_usufruct")
        and not c.get("shared_listing")
        and not c.get("low_price_outlier")
        and not c.get("high_price_outlier")
    )


def main():
    if not STORE.exists() or not COMPS.exists():
        print("need data/auctions.json and data/comps.json; run scraper.py + comps.py first", file=sys.stderr)
        return

    records = [r for r in json.loads(STORE.read_text()) if r.get("status", "active") == "active"]
    comps = json.loads(COMPS.read_text())

    out = {}
    viable = priced_under = 0
    for r in records:
        area = r.get("area_m2")
        c = comps.get(str(r["id"])) or comps.get(r["id"])
        if not area or r.get("type") not in CEILING_TYPES or not usable_comp(c):
            continue

        v_market = c["median_ppsqm"] * area
        v_resale = v_market * RESALE_HAIRCUT
        reno = RENO_PER_M2 * area if r.get("type") in RENO_TYPES else 0.0
        ceiling = (v_resale * (1 - MARGIN) - reno - LEGAL_CONTINGENCY) / (1 + TXN_COST_PCT)
        ceiling = round(max(0.0, ceiling))

        price = r.get("price_eur")
        # headroom: how far the current starting price sits below the ceiling.
        # positive = room to bid; negative = starting price already over the ceiling.
        headroom_pct = round(100 * (ceiling - price) / ceiling, 1) if (price and ceiling) else None

        out[r["id"]] = {
            "ceiling_eur": ceiling,
            "viable": ceiling > 0,
            "resale_value_eur": round(v_resale),
            "reno_eur": round(reno),
            "headroom_pct": headroom_pct,
            "basis": c.get("basis"),
            "sample_size": c.get("sample_size"),
        }
        if ceiling > 0:
            viable += 1
        if headroom_pct is not None and headroom_pct >= 0:
            priced_under += 1

    OUT.write_text(json.dumps(
        {"assumptions": {
            "resale_haircut": RESALE_HAIRCUT, "margin": MARGIN, "reno_per_m2": RENO_PER_M2,
            "txn_cost_pct": TXN_COST_PCT, "legal_contingency": LEGAL_CONTINGENCY,
        }, "lots": out},
        ensure_ascii=False, indent=1))
    print(f"WALKAWAY {len(out)} ceilings computed | {viable} viable | "
          f"{priced_under} already priced at/below their ceiling",
          file=sys.stderr)


if __name__ == "__main__":
    main()
