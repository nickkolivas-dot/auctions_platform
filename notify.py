#!/usr/bin/env python3
"""
Emails a digest of NEW listings after a scan.
Credentials come from env (GitHub Secrets) — never hard-coded.
Required env: SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS MAIL_TO
Optional filter env (narrows the email, not the scan):
  ALERT_TYPES=Land,Residential   ALERT_REGION=Πελοποννήσου   ALERT_MAX_PRICE=50000
  ALERT_LOC=Κατάκολο                (substring match on municipality/address/title)
Exits quietly (no send) when nothing new matches.
"""
import html, json, os, smtplib, sys
from email.mime.text import MIMEText
from pathlib import Path

DATA = Path("data")
meta = json.loads((DATA / "meta.json").read_text()) if (DATA / "meta.json").exists() else {}
new_ids = set(meta.get("new_ids", []))
if not new_ids:
    print("no new listings; skip email"); sys.exit(0)

rows = [r for r in json.loads((DATA / "auctions.json").read_text()) if r["id"] in new_ids]

drops_by_id = {}
if (DATA / "drops.json").exists():
    for d in json.loads((DATA / "drops.json").read_text()):
        if d.get("has_drop"):
            drops_by_id[d["latest_id"]] = d

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
    print("new listings exist but none match ALERT_* filter; skip email"); sys.exit(0)

rows.sort(key=lambda r: (r.get("price_eur") or 1e15))
eur = lambda n: "€{:,.0f}".format(n) if n else "—"
esc = lambda s: html.escape(str(s)) if s else ""
cards = "".join(f"""
<tr><td style="padding:12px 0;border-bottom:1px solid #e5e1d8">
 <a href="{esc(r['url'])}" style="font:600 15px sans-serif;color:#0a5960;text-decoration:none">{esc(r['title'])}</a><br>
 <span style="font:600 18px Georgia,serif;color:#12232e">{eur(r.get('price_eur'))}</span>
 {f'<span style="font:700 12px monospace;color:#a4402f">&nbsp;🔻 −{drops_by_id[r["id"]]["drop_pct"]}% vs prior round</span>' if r['id'] in drops_by_id else ''}
 <span style="font:12px monospace;color:#6c7a82">
  &nbsp;·&nbsp;{r.get('area_m2') or '—'} m²&nbsp;·&nbsp;{esc(r['type'])}&nbsp;·&nbsp;
  {esc(r.get('municipality') or '')} , {esc(r.get('region') or '')}&nbsp;·&nbsp;⚖ {esc(r.get('auction_date') or '—')}</span>
</td></tr>""" for r in rows)

html = f"""<div style="max-width:640px;margin:auto;font-family:sans-serif">
<h2 style="font-family:Georgia,serif;color:#12232e">{len(rows)} new auction listing{'s' if len(rows)!=1 else ''}</h2>
<p style="color:#6c7a82;font-size:13px">Scan {meta.get('last_run','')} · source eauction24.gr</p>
<table style="width:100%;border-collapse:collapse">{cards}</table>
<p style="color:#a4402f;font-size:12px;margin-top:18px">Verify on eauction.gr + legal/engineer title check before bidding.</p>
</div>"""

msg = MIMEText(html, "html", "utf-8")
msg["Subject"] = f"[Auctions] {len(rows)} new listing{'s' if len(rows)!=1 else ''}"
msg["From"] = os.environ["SMTP_USER"]
msg["To"] = os.environ["MAIL_TO"]
with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
    s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
print(f"emailed {len(rows)} listings to {os.environ['MAIL_TO']}")
