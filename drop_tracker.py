#!/usr/bin/env python3
"""
Links the same physical property across re-auction rounds (each round gets a
new eauction24 id) and flags floor-price cuts.

Reads data/auctions.json, which now keeps delisted lots (status="removed")
rather than dropping them, so past rounds stay available to match against.
Writes data/drops.json.

Match key: region + municipality + normalized address. area_m2 is a sanity
check, not part of the key -- if two rounds under the same address key
disagree on area by more than 5%, the group is kept (for inspection) but
marked area_mismatch and excluded from has_drop, since address text alone
was too weak a match to trust.

Also flags recency: recent_drop (>=1 price cut in the last 30 days) and
multi_cut (>=2 cuts in that window) -- a property cut twice in a month is
a stronger "motivated seller" signal than the usual zero-or-one pattern.
"""
import json, re, sys
from datetime import date, timedelta
from pathlib import Path

DATA = Path("data")
STORE = DATA / "auctions.json"
OUT = DATA / "drops.json"
RECENT_WINDOW_DAYS = 30


def norm(s):
    s = (s or "").strip().lower()
    s = re.sub(r"[.,·\-–—'\"()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def area_agrees(a, b, tol=0.05):
    if a is None or b is None:
        return True
    if a == 0 or b == 0:
        return a == b
    return abs(a - b) / max(a, b) <= tol


def recent_cuts(rounds, window_start):
    """Count round-to-round price decreases whose later round started within the window."""
    n = 0
    for prev_r, cur_r in zip(rounds, rounds[1:]):
        pp, cp = prev_r["price_eur"], cur_r["price_eur"]
        if pp is not None and cp is not None and cp < pp and (cur_r.get("first_seen") or "") >= window_start:
            n += 1
    return n


def main():
    if not STORE.exists():
        print("no data/auctions.json yet; run scraper.py first", file=sys.stderr)
        return

    window_start = (date.today() - timedelta(days=RECENT_WINDOW_DAYS)).isoformat()
    groups = {}
    for r in json.loads(STORE.read_text()):
        addr_key = norm(r.get("address"))
        if not addr_key:
            continue  # no address text -> can't safely link across rounds
        groups.setdefault((r.get("region"), r.get("municipality"), addr_key), []).append(r)

    drops = []
    for (region, municipality, addr_key), rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (r.get("auction_date") or r.get("first_seen") or ""))
        areas = [r.get("area_m2") for r in rows if r.get("area_m2") is not None]
        area_mismatch = any(not area_agrees(a, b) for a, b in zip(areas, areas[1:]))
        rounds = [{
            "id": r["id"], "url": r.get("url"), "title": r.get("title"),
            "auction_date": r.get("auction_date"), "first_seen": r.get("first_seen"),
            "status": r.get("status", "active"), "price_eur": r.get("price_eur"),
            "area_m2": r.get("area_m2"),
        } for r in rows]
        prices = [r["price_eur"] for r in rounds if r["price_eur"] is not None]
        has_drop = not area_mismatch and len(prices) >= 2 and prices[-1] < prices[0]
        cuts_30d = 0 if area_mismatch else recent_cuts(rounds, window_start)
        drops.append({
            "key": f"{region}|{municipality}|{addr_key}",
            "region": region, "municipality": municipality,
            "address": rows[-1].get("address"),
            "rounds": rounds,
            "rounds_count": len(rounds),
            "area_mismatch": area_mismatch,
            "has_drop": has_drop,
            "first_price": prices[0] if prices else None,
            "latest_price": prices[-1] if prices else None,
            "drop_pct": round(100 * (1 - prices[-1] / prices[0]), 1) if has_drop and prices[0] else None,
            "latest_id": rounds[-1]["id"],
            "recent_cuts_30d": cuts_30d,
            "recent_drop": cuts_30d >= 1,
            "multi_cut": cuts_30d >= 2,
        })

    drops.sort(key=lambda d: (not d["multi_cut"], not d["has_drop"], -(d["drop_pct"] or 0)))
    OUT.write_text(json.dumps(drops, ensure_ascii=False, indent=1))
    flagged = sum(1 for d in drops if d["has_drop"])
    multi = sum(1 for d in drops if d["multi_cut"])
    print(f"TRACKED {len(drops)} re-auctioned lots | DROPS {flagged} | MULTI-CUT (2+/30d) {multi}", file=sys.stderr)


if __name__ == "__main__":
    main()
