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
  cuts, writes `data/drops.json`.
- `notify.py`   — emails new listings (SMTP via env), flags price cuts. Optional ALERT_* filter.
- `index.html`  — dashboard; fetches `data/auctions.json` + `data/drops.json`, falls back to seed.
- `.github/workflows/scan.yml` — cron 09:00 + 17:00 Athens: scrape → link rounds → email → commit.
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
Drop-tracker shipped (`drop_tracker.py`, `data/drops.json`, dashboard + email
badges). Next up per ROADMAP.md Phase 1: discount score — €/m² vs municipality
comps, walk-away price per lot. See tasks/todo.md.
