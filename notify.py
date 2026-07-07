#!/usr/bin/env python3
"""
Emails a digest of NEW listings after a scan.
Credentials come from env (GitHub Secrets) — never hard-coded.
Env: SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS MAIL_TO — skips quietly (no send,
exit 0) if any of these aren't set yet, so a scan before Secrets are
configured still commits data instead of failing the workflow.
Optional filter env (narrows the email, not the scan):
  ALERT_TYPES=Land,Residential   ALERT_REGION=Πελοποννήσου   ALERT_MAX_PRICE=50000
  ALERT_LOC=Κατάκολο                (substring match on municipality/address/title)
FORCE_EMAIL=1 sends the current price-drop list instead of skipping when a
run finds nothing new — useful for testing or an on-demand check-in, since
the routine scan is new-only by design (it'd otherwise re-email the whole
archive every run).
Exits quietly (no send) when nothing new/forced matches.
"""
import html, json, os, smtplib, sys, urllib.parse
from email.mime.text import MIMEText
from pathlib import Path

DASHBOARD_URL = "https://nickkolivas-dot.github.io/auctions_platform/"
DATA = Path("data")
meta = json.loads((DATA / "meta.json").read_text()) if (DATA / "meta.json").exists() else {}
new_ids = set(meta.get("new_ids", []))

drops_by_id = {}
if (DATA / "drops.json").exists():
    for d in json.loads((DATA / "drops.json").read_text()):
        if d.get("has_drop"):
            drops_by_id[d["latest_id"]] = d

is_drop_digest = False
if not new_ids:
    if os.environ.get("FORCE_EMAIL", "").lower() not in ("1", "true"):
        print("no new listings; skip email"); sys.exit(0)
    if not drops_by_id:
        print("forced send requested, but no price drops to report either; skip email"); sys.exit(0)
    is_drop_digest = True
    new_ids = set(drops_by_id)

required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASS", "MAIL_TO"]
missing = [v for v in required if not os.environ.get(v)]
if missing:
    print(f"missing {', '.join(missing)}; skip email (add repo Secrets to enable)"); sys.exit(0)

rows = [r for r in json.loads((DATA / "auctions.json").read_text()) if r["id"] in new_ids]

# optional filter
types = [t.strip() for t in os.environ.get("ALERT_TYPES", "").split(",") if t.strip()]
region = os.environ.get("ALERT_REGION", "").strip()
maxp = float(os.environ.get("ALERT_MAX_PRICE", "0") or 0)
loc = os.environ.get("ALERT_LOC", "").strip().lower()
def keep(r):
    if types and r["type"] not in types: return False
    if region and r.get("region") != region: return False
    if maxp and (r.get("price_eur") or 0) > maxp: return False
    if loc and loc not in ((r.get("municipality") or "") + (r.get("address") or "") + (r.get("title") or "")).lower(): return False
    return True
rows = [r for r in rows if keep(r)]
if not rows:
    print(f"{'price drops' if is_drop_digest else 'new listings'} exist but none match ALERT_* filter; skip email"); sys.exit(0)

rows.sort(key=lambda r: (r.get("price_eur") or 1e15))
eur = lambda n: "€{:,.0f}".format(n) if n else "—"
esc = lambda s: html.escape(str(s)) if s else ""

if is_drop_digest:
    dash_params = {"drop": "1"}
else:
    dash_params = {}
    if types: dash_params["type"] = ",".join(types)
    if region: dash_params["region"] = region
    if maxp: dash_params["pmax"] = str(int(maxp))
    if loc: dash_params["loc"] = loc
    if not dash_params: dash_params = {"new": "1"}
dashboard_link = DASHBOARD_URL + "?" + urllib.parse.urlencode(dash_params)

PLACEHOLDER_IMG = "https://placehold.co/110x80/e9e5db/6c7a82?text=%C2%B7"

def card(r):
    drop = drops_by_id.get(r["id"])
    facts = " · ".join(filter(None, [
        f"{r['area_m2']:g} m²" if r.get("area_m2") else None,
        r.get("type"),
        f"{r['bedrooms']} bd" if r.get("bedrooms") else None,
        ", ".join(filter(None, [r.get("municipality"), r.get("region")])) or None,
        f"⚖ {r['auction_date']}" if r.get("auction_date") else None,
    ]))
    img = esc(r.get("image") or PLACEHOLDER_IMG)
    return f"""
<table role="presentation" width="100%" style="margin-bottom:12px;border:1px solid #e5e1d8;border-radius:8px;border-collapse:separate">
<tr>
<td width="110" style="padding:0;border-radius:8px 0 0 8px;overflow:hidden">
<a href="{esc(r['url'])}"><img src="{img}" width="110" height="80" style="display:block;width:110px;height:80px;object-fit:cover" alt=""></a>
</td>
<td style="padding:10px 12px;vertical-align:top">
<a href="{esc(r['url'])}" style="font:600 14px sans-serif;color:#0a5960;text-decoration:none">{esc(r['title'])}</a><br>
<span style="font:600 17px Georgia,serif;color:#12232e">{eur(r.get('price_eur'))}</span>
{f'<span style="font:700 11px monospace;color:#a4402f">&nbsp;🔻 −{drop["drop_pct"]}% vs prior round</span>' if drop else ''}
<br><span style="font:11.5px monospace;color:#6c7a82">{esc(facts)}</span>
</td>
</tr>
</table>"""

cards = "".join(card(r) for r in rows)

label = "propert" + ("y" if len(rows) == 1 else "ies") + " with a price cut" if is_drop_digest else \
        "new auction listing" + ("" if len(rows) == 1 else "s")
body = f"""<div style="max-width:640px;margin:auto;font-family:sans-serif">
<h2 style="font-family:Georgia,serif;color:#12232e">{len(rows)} {label}</h2>
<p style="color:#6c7a82;font-size:13px">Scan {meta.get('last_run','')} · source eauction24.gr ·
<a href="{esc(dashboard_link)}" style="color:#0a5960">view &amp; filter on the dashboard →</a></p>
{cards}
<p style="color:#a4402f;font-size:12px;margin-top:18px">Verify on eauction.gr + legal/engineer title check before bidding.</p>
</div>"""

msg = MIMEText(body, "html", "utf-8")
msg["Subject"] = f"[Auctions] {len(rows)} {label}"
msg["From"] = os.environ["SMTP_USER"]
msg["To"] = os.environ["MAIL_TO"]
with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
    s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
print(f"emailed {len(rows)} listings to {os.environ['MAIL_TO']}")
