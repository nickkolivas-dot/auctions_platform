# CLAUDE.md — Greek Auction Monitor

## What this is
Twice-daily monitor of Greek judicial property auctions. Scrapes public listings,
diffs for new lots, emails a digest, serves a static dashboard. Personal tool
(you + partner) for sourcing investment opportunities. Not a platform.

## Architecture (don't add to this without reason)
- `scraper.py`  — pulls 13 regions from eauction24.gr, parses schema.org
  `RealEstateListing` JSON-LD, merges into `data/auctions.json` (full history —
  delisted lots are kept with `status: removed`, not deleted), tags `first_seen`.
- `drop_tracker.py` — links the same property across re-auction rounds (new id
  each round) by region + municipality + normalized address, flags floor-price
  cuts (plus recent/multi-cut within 30 days), writes `data/drops.json`.
- `comps.py` — scores each listing's €/m² against its municipality's median
  (region fallback when too few comps). Guards against two verified data
  quirks: nominal-price partial-ownership-share auctions, and the same
  parcel re-listed as multiple fractional shares — both would otherwise
  corrupt the median. Writes `data/comps.json`.
- `notify.py`   — emails new listings (SMTP via env), flags price cuts + comps. Optional ALERT_* filter.
  Optional AI curation (OPENAI_API_KEY or ANTHROPIC_API_KEY) reads listing
  descriptions for risk flags and separates a "Worth a look" section from
  everything else. Falls back to the plain list with no key or on any
  API failure — never blocks the send.
- `index.html`  — dashboard; fetches `data/auctions.json` + `data/drops.json` + `data/comps.json`, falls back to seed.
- `.github/workflows/scan.yml` — cron 09:00 + 17:00 Athens: scrape → link rounds → score comps → email → commit.
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
Drop-tracker and discount score (comps.py) both shipped. Next up per
ROADMAP.md Phase 1: walk-away price per lot (a "don't bid above this"
ceiling, separate from the comps score). See tasks/todo.md. Also open:
research whether Landea (second aggregator, already used manually per
ROADMAP.md Phase 0) is safely scrapable before building anything against it.
