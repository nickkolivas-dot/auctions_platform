# CLAUDE.md — Greek Auction Monitor

## What this is
Twice-daily monitor of Greek judicial property auctions. Scrapes public listings,
diffs for new lots, emails a digest, serves a static dashboard. Personal tool
(you + partner) for sourcing investment opportunities. Not a platform.

## Architecture (don't add to this without reason)
- `scraper.py`  — pulls 13 regions from eauction24.gr, parses schema.org
  `RealEstateListing` JSON-LD, merges into `data/auctions.json` (full history —
  delisted lots are kept with `status: removed`, not deleted), tags `first_seen`.
  Also runs `detect_ownership()`: Greek auctions sell distinct legal rights
  (full/πλήρης, bare/ψιλή κυριότητα, usufruct/επικαρπία, shared/συγκυριότητα)
  stated in the listing text — tagged as `ownership_type` on every record.
  And `detect_occupancy()` → `occupancy` (vacant/leased/occupied/unknown):
  HIGH-PRECISION, LOW-RECALL by design — verified that the public aggregator
  almost never states occupancy (the real answer is in the appraiser's report
  on the logged-in site, which we don't scrape), so it only asserts a status
  when the text is unambiguous and defaults to `unknown`. Never assume a
  building is empty from silence.
- `drop_tracker.py` — links the same property across re-auction rounds (new id
  each round) by region + municipality + normalized address, flags floor-price
  cuts (plus recent/multi-cut within 30 days), writes `data/drops.json`.
- `comps.py` — scores each listing's €/m² against its municipality's median
  (region fallback when too few comps). Guards against three verified data
  quirks that would otherwise corrupt the median: nominal-price partial-
  ownership-share auctions, the same parcel re-listed as multiple fractional
  shares, and bare-ownership/usufruct sales (excluded from the baseline
  entirely, not just flagged — comparing their price to a full-ownership
  median isn't meaningful at all). Writes `data/comps.json`.
- `walkaway.py` — per-lot "don't bid above this" ceiling, deliberately SEPARATE
  from the comps discount. `ceiling = (resale*(1-margin) - reno - legal) / (1+txn)`,
  resale anchored to the comps median €/m². BUILDINGS ONLY — the €/m²×area value
  model breaks for raw land (value swings with buildability, not area; verified a
  9,375 m² non-buildable farm came out "worth" €5M). All assumptions are env vars
  (`WALKAWAY_*`), so the model re-tunes in one place. Writes `data/walkaway.json`.
- `notify.py`   — emails new listings (SMTP via env), flags price cuts + comps.
  Filters: ALERT_TYPES/REGION/MAX_PRICE, plus ALERT_AREAS — a ";"-separated
  watchlist OR-list (bare token = exact region/municipality match; "~token" =
  locality substring on address+title) for focusing on specific areas across
  regions. Bare-ownership/usufruct listings are hard-excluded unconditionally
  (`INCLUDE_BARE_OWNERSHIP=1` to override). Cards show the walk-away max-bid
  ceiling and, for buildings, a known occupancy status.
  RANKING — the "Top N to act on today" (TOP_N, default 5) is driven by a
  deterministic buy-to-sell `signals()` model in `signals()`/`rank_score()`
  (ONE source of truth for both the score and the per-card "why" pills):
  discount vs local €/m² median, motivated-seller (re-auction round count,
  drop %, multi-cut in 30d), urgency (imminent auction date), and liquidity
  (parking in the scarce/dense central Attica belt `PARKING_SCARCE`,
  `HIGH_DEMAND` municipalities, low-ticket ≤€40k). All deterministic —
  NO LLM KEY NEEDED for the Top section. Optional AI curation (OPENAI_API_KEY
  or ANTHROPIC_API_KEY) only ADDS potential_tags to the score and risk_flags
  that disqualify a lot from the Top; the LLM never scores or ranks. Falls
  back cleanly with no key or on any API failure — never blocks the send.
  The PARKING_SCARCE/HIGH_DEMAND sets are an editable market-knowledge
  heuristic, not derived from data.
- `index.html`  — dashboard; fetches `auctions.json` + `drops.json` + `comps.json`
  + `walkaway.json`, falls back to seed. Shows per-card max-bid ceiling +
  occupancy caveat; "🎯 First-deal mode" preset = full ownership + 10%+ below
  median + not debtor-occupied (`?firstdeal=1`).
- `.github/workflows/scan.yml` — once every morning at 09:00 Athens (a `gate`
  job straddles EU DST: crons fire 06:00 & 07:00 UTC, only the 09:00-Athens one
  proceeds; workflow_dispatch bypasses the gate to "send now"): scrape → link
  rounds → comps → walk-away → morning digest (DAILY_DIGEST=1) → commit.
- Runs on GitHub Actions. No server, no agent runner, no database.

## Hard rules
- **Public data only.** Scrape logged-out aggregator pages. NEVER scrape the
  logged-in eauction.gr — registration = ToS acceptance = no automated access.
- **No secrets in files.** SMTP creds live in GitHub Secrets, referenced as
  `${{ secrets.* }}`. Never hard-code, never echo, never commit a .env.
- **`data/` IS committed.** The longitudinal history is the asset — do not gitignore it.
- Scraper depends on eauction24's JSON-LD. If a scan returns 0 rows, their markup
  changed — fix selectors, don't silently pass.

## Working style
- SME / minimal diffs. Root-cause fixes, no temporary patches.
- Verify before "done": run a subset scrape and show output/diff.
- Test subset first: `python scraper.py "Αττικής"` before a full 13-region run.

## Next task
Drop-tracker, discount score (comps.py), ownership-type detection/exclusion,
AI-curated "Top N of the day" ranking, the walk-away price ceiling
(walkaway.py), occupancy detection, and dashboard first-deal mode are all
shipped. Open items:
- Research whether Landea (second aggregator, already used manually per
  ROADMAP.md Phase 0) is safely scrapable before building anything against it.
- BOTH occupancy AND ownership-type are essentially absent from eauction24's
  public pages (verified 2026-07-14 by fetching real detail pages: 0 hits for
  ψιλ/επικαρπ/πλήρης-κυριότητ anywhere on the page, not just the JSON-LD desc;
  occupancy ~0.2%). detect_ownership/detect_occupancy correctly handle the rare
  explicitly-stated cases and default safely, but their recall on this source is
  near zero. The reliable source for both is the appraiser's report + κατασχετήρια
  έκθεση in the eauction.gr case file — a MANUAL due-diligence step by design, not
  scrapable (logged-in = ToS). The reliable public signals are price/area/discount/
  drops; the tool screens on those, the human does the legal/condition check.
- The WALKAWAY_* assumptions ship with defaults (25% margin, €350/m² reno,
  0.90 resale, 6% txn); tune them from real closed deals as they accumulate.
