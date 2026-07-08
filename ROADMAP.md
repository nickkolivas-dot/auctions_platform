# Auction Monitor — Build Roadmap

## Read this first (when it feels confusing)
We are **not** building a platform or a new website.
We are extending **one small tool that already exists and works**.
It runs itself, for free, on GitHub. A "platform" only happens later — and only if it makes money.

## What runs where
- **Collector + Monitor + Scorer** = a few Python scripts in **one GitHub repo**
- **Schedule** = GitHub Actions (free cron, 2×/day) — already set up
- **Dashboard ("the website")** = one HTML file on GitHub Pages — already built
- **No server. No OpenClaw. No logins.** Private tool for you + your partner.

---

## Phase 0 — Setup (this week, zero code)
- [ ] Register on eauction.gr (TaxisNet) — you
- [ ] Register on eauction.gr (TaxisNet) — best man
- [ ] Saved-search email alerts on Landea + eauction24 — both of you
- [ ] Push the existing repo to GitHub → enable Pages + Actions
- [ ] Add Gmail app password as repo Secrets (turns email alerts on)

## Phase 1 — The tool (~70% done already)
- [x] Collector: scraper across 13 regions
- [x] Dashboard: filter by type / region / price / m² / new
- [x] Email digest of new listings
- [x] Cron 2×/day
- [x] **Drop-tracker**: link a lot across re-auction rounds, flag floor cuts
- [x] **Discount score**: €/m² vs municipality comps (region fallback when too few comps; outlier/shared-listing detection for partial-ownership sales)
- [ ] **Walk-away price per lot**: still open — a computed "don't bid above this" ceiling, separate from the comps score  ← NEXT

## Phase 2 — Prove it (dogfood, over months)
- [ ] Deal log: lot / comps estimate / discount / decision / outcome
- [ ] Drop-history dataset builds automatically from the daily runs
- [ ] **Greenlight target** (decide now): e.g. 3 profitable deals, OR one advisor/servicer who will pay for the drop-data
- [ ] **Kill criterion** (decide now): if by <date> there's no sign of value → stop, keep it as a personal tool. No guilt.

## Phase 3 — Commercialise (ONLY if Phase 2 greenlights)
- Only now does "platform" enter: user accounts, hosted DB, payments.
- What you'd actually sell = **drop-history data + your track record**, not a listings site.

---

## Deliberately NOT doing (anti-scope-creep)
- ✗ No custom platform / SaaS build now
- ✗ No OpenClaw / agent runner for the scrape (deterministic → GitHub Actions)
- ✗ No scraping the logged-in eauction.gr (ToS) — manual due diligence there only
- ✗ No chasing bidder-counts (capital-gated, not worth it)

## The one sentence
Extend the tool you have. Prove it with your own money. Only build a "platform" if someone will pay.
