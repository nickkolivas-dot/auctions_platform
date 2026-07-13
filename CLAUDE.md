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
- `notify.py`   — emails new listings (SMTP via env), flags price cuts + comps. Optional ALERT_* filter.
  Bare-ownership/usufruct listings are hard-excluded from the email
  unconditionally (`INCLUDE_BARE_OWNERSHIP=1` to override), independent of
  whether AI curation is configured. Optional AI curation (OPENAI_API_KEY or
  ANTHROPIC_API_KEY) reads listing descriptions for risk_flags and
  potential_tags (buildable, view, leased-with-income, etc) — the LLM never
  scores or ranks; a deterministic `rank_score()` in Python (comps discount +
  price cuts + a fixed point value per potential_tag) picks the "Top N of the
  day" (TOP_N, default 5) from listings with zero risk flags. Falls back to
  the plain list with no key or on any API failure — never blocks the send.
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
Drop-tracker, discount score (comps.py), ownership-type detection/exclusion,
and AI-curated "Top N of the day" ranking are all shipped. Next up per
ROADMAP.md Phase 1: walk-away price per lot (a "don't bid above this"
ceiling, separate from the comps score). See tasks/todo.md. Also open:
research whether Landea (second aggregator, already used manually per
ROADMAP.md Phase 0) is safely scrapable before building anything against it.
