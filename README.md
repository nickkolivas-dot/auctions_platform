# Greek Auction Monitor

Scrapes public judicial-auction listings (eauction24.gr) twice daily, diffs
against the last run, **emails new listings**, and serves a filterable dashboard.

## Files
- `scraper.py`  – pulls all 13 regions, parses schema.org JSON-LD, tags NEW listings, keeps full history (delisted lots marked `removed`, not deleted)
- `drop_tracker.py` – links a lot across re-auction rounds by address/locality, flags floor-price cuts → `data/drops.json`
- `notify.py`   – emails a digest of new listings, flags price cuts (optional filter)
- `index.html`  – dashboard (type / region / price / m² / new-only / price-reduced)
- `.github/workflows/scan.yml` – cron 09:00 + 17:00 Athens, scrape → link rounds → email → commit

## Deploy (~20 min, free)
### 1. Repo + dashboard
1. Create a **public** GitHub repo, push these files.
2. Settings → **Pages** → Source `main` / root → dashboard at `https://<you>.github.io/<repo>/`.
3. Actions → enable workflows → **Run workflow** to test.

### 2. Email (Gmail example)
You create the credentials — they never live in code.
1. Google Account → Security → 2-Step Verification → **App passwords** → generate one.
2. Repo → Settings → Secrets and variables → **Actions** → add **secrets**:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = your Gmail address
   - `SMTP_PASS` = the 16-char app password
   - `MAIL_TO`   = where alerts go
3. (Optional) narrow the email via repo **variables** (same screen, "Variables" tab):
   - `ALERT_TYPES` = `Land,Residential`
   - `ALERT_REGION` = `Πελοποννήσου`
   - `ALERT_MAX_PRICE` = `50000`
   - `ALERT_LOC` = `Κατάκολο`
   Leave all unset → email every new listing.

## Local run
    pip install -r requirements.txt
    python scraper.py "Αττικής" "Πελοποννήσου"   # subset
    python scraper.py                              # all regions
    python drop_tracker.py                         # link re-auction rounds, flag price cuts
    open index.html

## Automation — which engine
| Engine | Runs unattended? | Best for |
|---|---|---|
| GitHub Actions (this repo) | Yes (cloud, laptop off), free | the deterministic scrape + email ← use this |
| Claude Code Routines (claude.ai/code/scheduled) | Yes (Anthropic cloud) | a judgment layer: score/curate listings, then email |
| Cowork scheduled tasks | Only while Mac awake + Desktop app open | "brief me when I open the laptop" |

## Notes
- Seed data embedded so the dashboard works before first scan.
- `first_seen` drives the NEW badge, "only new" filter, and the email diff.
- Covers judicial auctions only. Bank-servicer REO (doValue/Cepal/Intrum) is a separate source — not yet included.
- Always verify a listing on eauction.gr (Taxisnet) + legal/engineer title check before bidding.
- Keep the 2×/day cadence; don't hammer the source.
