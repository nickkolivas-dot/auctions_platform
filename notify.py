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

Optional curation (OPENAI_API_KEY or ANTHROPIC_API_KEY -- OpenAI wins if both
are set): the LLM only reads each listing's free-text description for what
the structured fields miss (occupancy, liens/mortgages mentioned, access
issues, missing permits) and returns risk_flags + a one-line note -- it does
NOT decide which listings are good. Ranking into "Top N of the day" (TOP_N,
default 5) is a separate, deterministic score in Python from comps.py's
vs-median discount and drop_tracker.py's price-cut %; a listing only
qualifies if it has zero risk flags AND a positive score. Everything else
collapses to one line instead of a full card, flags shown inline. This is
pattern-matching on scraped text, not legal or financial advice -- it does
not replace the title/engineer check. No key set, or the API call fails for
any reason -> silently falls back to the plain full-list email exactly as
before. Never blocks the send. Model overridable via OPENAI_MODEL / ANTHROPIC_MODEL.
"""
import html, json, os, smtplib, sys, urllib.parse
import requests
from email.mime.text import MIMEText
from pathlib import Path

DASHBOARD_URL = "https://nickkolivas-dot.github.io/auctions_platform/"
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-4-5-20251001"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL") or "gpt-5.6-sol"
MAX_CURATE = 30  # bounds cost/latency per run; rows beyond this just show uncurated
TOP_N = int(os.environ.get("TOP_N") or 5)  # daily cap on the "Top picks" section
DATA = Path("data")
meta = json.loads((DATA / "meta.json").read_text()) if (DATA / "meta.json").exists() else {}
new_ids = set(meta.get("new_ids", []))

drops_by_id = {}
if (DATA / "drops.json").exists():
    for d in json.loads((DATA / "drops.json").read_text()):
        if d.get("has_drop"):
            drops_by_id[d["latest_id"]] = d

comps_by_id = {}
if (DATA / "comps.json").exists():
    comps_by_id = {int(k): v for k, v in json.loads((DATA / "comps.json").read_text()).items()}

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

# hard exclusion, always on unless explicitly overridden: bare ownership (ψιλή κυριότητα --
# title without the right to use/occupy until a usufruct ends) and usufruct-only (επικαρπία)
# sales aren't full-control real estate at all, regardless of how good the price looks.
if os.environ.get("INCLUDE_BARE_OWNERSHIP", "").lower() not in ("1", "true"):
    excluded_ownership = [r for r in rows if r.get("ownership_type") in ("bare", "usufruct")]
    if excluded_ownership:
        print(f"excluded {len(excluded_ownership)} bare-ownership/usufruct listing(s): "
              f"{[r['id'] for r in excluded_ownership]}", file=sys.stderr)
    rows = [r for r in rows if r.get("ownership_type") not in ("bare", "usufruct")]

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


POTENTIAL_TAGS = ["buildable", "sea_or_scenic_view", "leased_with_income",
                   "renovated_or_good_condition", "prime_frontage_or_corner", "near_amenities"]
# points added in rank_score() per tag found -- kept here, in code, not left to the LLM,
# so the actual weighting stays auditable and tunable without touching the prompt
POTENTIAL_WEIGHTS = {"buildable": 15, "sea_or_scenic_view": 8, "leased_with_income": 10,
                      "renovated_or_good_condition": 6, "prime_frontage_or_corner": 5, "near_amenities": 4}
POTENTIAL_LABELS = {"buildable": "buildable", "sea_or_scenic_view": "view",
                     "leased_with_income": "leased/income", "renovated_or_good_condition": "renovated",
                     "prime_frontage_or_corner": "prime frontage", "near_amenities": "near amenities"}

CURATION_SYSTEM_PROMPT = (
    "You help two people screen Greek judicial property auction listings. You are not a "
    "financial or legal advisor. Your only job is reading the free-text description each "
    "listing already has -- you do not decide which listings are good investments; a separate, "
    "deterministic calculation (price-per-sqm vs the local median, price cuts, and a small fixed "
    "bonus per potential_tag you report) ranks them, and your output only feeds that calculation "
    "and a red-flag check on top of it. For each listing: "
    "(1) read the description for anything a buyer should know that isn't in the structured "
    "fields -- occupancy BY THE DEBTOR (not a paying tenant), liens/mortgages mentioned, access "
    "issues, structural condition, missing permits, partial/undivided ownership share (a "
    "fraction of the property, not the whole thing); list every such issue in risk_flags as "
    "short phrases, in Greek or English as it appears -- empty list if genuinely nothing stands "
    "out, but do not invent reassurance where the description is merely silent; "
    "(2) separately, from potential_tags, pick every tag that is EXPLICITLY supported by the "
    "text -- do not guess or infer one that isn't actually stated: buildable (άρτιο και "
    "οικοδομήσιμο / εντός σχεδίου -- explicitly buildable/zoned, not merely land), "
    "sea_or_scenic_view (θέα θάλασσα or similar), leased_with_income (already rented to a "
    "paying tenant under a lease -- the OPPOSITE of debtor occupancy, do not confuse the two), "
    "renovated_or_good_condition (recently renovated / stated as excellent condition), "
    "prime_frontage_or_corner (frontage on a main road, or a corner plot), near_amenities "
    "(explicitly near transport/center/beach/school etc). Leave the list empty if none apply -- "
    "most listings will have zero or one tag, do not pad it; "
    "(3) write one factual sentence in 'note' grounded only in what's actually stated -- no "
    "hype words (avoid 'great deal', 'bulletproof', 'guaranteed', 'must buy'), and no restating "
    "the price/area/type numbers already shown elsewhere. If comp_warning is not null, name it "
    "in risk_flags too (e.g. 'shares an address with another listing -- possible partial "
    "share') even though you can't see the underlying data yourself."
)
CURATION_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "note": {"type": "string"},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                    "potential_tags": {"type": "array", "items": {"type": "string", "enum": POTENTIAL_TAGS}},
                },
                "required": ["id", "note", "risk_flags", "potential_tags"],
            },
        },
    },
    "required": ["results"],
}


def _call_anthropic(api_key, payload):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 8192,
            "system": CURATION_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "tools": [{"name": "curate_listings", "description": "Return a screening note for each listing",
                       "input_schema": CURATION_RESULT_SCHEMA}],
            "tool_choice": {"type": "tool", "name": "curate_listings"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    for block in resp.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "curate_listings":
            return block["input"]["results"]
    raise ValueError("no tool_use block in Anthropic response")


def _call_openai(api_key, payload):
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": CURATION_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "tools": [{"type": "function", "function": {"name": "curate_listings",
                       "description": "Return a screening note for each listing",
                       "parameters": CURATION_RESULT_SCHEMA}}],
            "tool_choice": {"type": "function", "function": {"name": "curate_listings"}},
        },
        timeout=60,
    )
    resp.raise_for_status()
    call = resp.json()["choices"][0]["message"]["tool_calls"][0]
    return json.loads(call["function"]["arguments"])["results"]


def curate(rows):
    """None = didn't run or failed (caller falls back to the plain list).
    Dict (possibly empty) = ran; keyed by listing id -> {note, risk_flags}. Ranking into
    "Top picks" is done separately in Python from comps/drop data, not by the LLM.
    Prefers OpenAI if OPENAI_API_KEY is set, else Anthropic if ANTHROPIC_API_KEY is set."""
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not openai_key and not anthropic_key:
        return None
    batch = rows[:MAX_CURATE]
    payload = [{
        "id": r["id"],
        "title": r.get("title"),
        "type": r.get("type"),
        "price_eur": r.get("price_eur"),
        "area_m2": r.get("area_m2"),
        "municipality": r.get("municipality"),
        "region": r.get("region"),
        "description": (r.get("description") or "")[:400],
        "ownership_type": r.get("ownership_type", "full"),
        "vs_median_pct": (comps_by_id.get(r["id"]) or {}).get("vs_median_pct"),
        "comp_basis": (comps_by_id.get(r["id"]) or {}).get("basis"),
        "comp_warning": "shared_listing" if (comps_by_id.get(r["id"]) or {}).get("shared_listing")
            else "low_price_outlier" if (comps_by_id.get(r["id"]) or {}).get("low_price_outlier")
            else "high_price_outlier" if (comps_by_id.get(r["id"]) or {}).get("high_price_outlier") else None,
        "price_drop_pct": (drops_by_id.get(r["id"]) or {}).get("drop_pct"),
        "multi_cut": (drops_by_id.get(r["id"]) or {}).get("multi_cut", False),
    } for r in batch]

    try:
        results = _call_openai(openai_key, payload) if openai_key else _call_anthropic(anthropic_key, payload)
        return {item["id"]: item for item in results if "id" in item}
    except Exception as e:
        print(f"curation skipped: {e}", file=sys.stderr)
        return None


curation = curate(rows)

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

def comp_line(r):
    c = comps_by_id.get(r["id"])
    if not c:
        return ""
    if c.get("shared_listing"):
        return '<br><span style="font:700 11px monospace;color:#a4402f">⚠ shares address/size with another listing — may be a partial ownership share, verify</span>'
    if c.get("low_price_outlier"):
        return '<br><span style="font:700 11px monospace;color:#a4402f">⚠ unusually low price for the area — verify it isn\'t a partial-ownership sale</span>'
    if c.get("high_price_outlier"):
        return f'<br><span style="font:700 11px monospace;color:#a4402f">⚠ unusually high price vs {c["sample_size"]} comparable listings</span>'
    pct = c["vs_median_pct"]
    if pct <= -10:
        arrow = "↓"
        return f'<br><span style="font:700 11px monospace;color:#0a5960">{arrow}{abs(pct)}% vs {c["basis"]} median (n={c["sample_size"]})</span>'
    return ""


def curated_line(curated):
    if not curated:
        return ""
    note = curated.get("note")
    flags = curated.get("risk_flags") or []
    tags = curated.get("potential_tags") or []
    flags_html = "".join(
        f'<span style="display:inline-block;background:#fbe4d5;color:#a4402f;font:600 10px monospace;'
        f'padding:2px 6px;border-radius:10px;margin:4px 4px 0 0">⚠ {esc(f)}</span>' for f in flags
    )
    tags_html = "".join(
        f'<span style="display:inline-block;background:#e3efe1;color:#0a5960;font:600 10px monospace;'
        f'padding:2px 6px;border-radius:10px;margin:4px 4px 0 0">+ {esc(POTENTIAL_LABELS.get(t, t))}</span>' for t in tags
    )
    out = f'<br><span style="font:italic 12px sans-serif;color:#1b3341">{esc(note)}</span>' if note else ""
    if tags_html:
        out += f'<div style="margin-top:2px">{tags_html}</div>'
    if flags_html:
        out += f'<div style="margin-top:2px">{flags_html}</div>'
    return out


def card(r, curated=None):
    drop = drops_by_id.get(r["id"])
    ppsqm = round(r["price_eur"] / r["area_m2"]) if r.get("price_eur") and r.get("area_m2") else None
    facts = " · ".join(filter(None, [
        f"{r['area_m2']:g} m²" if r.get("area_m2") else None,
        f"{eur(ppsqm)}/m²" if ppsqm else None,
        r.get("type"),
        f"{r['bedrooms']} bd" if r.get("bedrooms") else None,
        ", ".join(filter(None, [r.get("municipality"), r.get("region")])) or None,
        f"⚖ {r['auction_date']}" if r.get("auction_date") else None,
    ]))
    img = esc(r.get("image") or PLACEHOLDER_IMG)
    if drop:
        prev_round = drop["rounds"][-2] if len(drop.get("rounds", [])) >= 2 else None
        prev_date = prev_round and (prev_round.get("auction_date") or prev_round.get("first_seen"))
        drop_emoji = "🔥" if drop.get("multi_cut") else "🔻"
        drop_label = f'{drop["drop_pct"]}% vs prior round' + \
            (f' (was ⚖ {prev_date})' if prev_date else '') + \
            (f' · {drop["recent_cuts_30d"]} cuts in 30d' if drop.get("multi_cut") else '')
    return f"""
<table role="presentation" width="100%" style="margin-bottom:12px;border:1px solid #e5e1d8;border-radius:8px;border-collapse:separate">
<tr>
<td width="110" style="padding:0;border-radius:8px 0 0 8px;overflow:hidden">
<a href="{esc(r['url'])}"><img src="{img}" width="110" height="80" style="display:block;width:110px;height:80px;object-fit:cover" alt=""></a>
</td>
<td style="padding:10px 12px;vertical-align:top">
<a href="{esc(r['url'])}" style="font:600 14px sans-serif;color:#0a5960;text-decoration:none">{esc(r['title'])}</a><br>
<span style="font:600 17px Georgia,serif;color:#12232e">{eur(r.get('price_eur'))}</span>
{f'<span style="font:700 11px monospace;color:#a4402f">&nbsp;{drop_emoji} −{drop_label}</span>' if drop else ''}
{comp_line(r)}
<br><span style="font:11.5px monospace;color:#6c7a82">{esc(facts)}</span>
{curated_line(curated)}
</td>
</tr>
</table>"""


def compact_row(r, curated):
    flags = (curated or {}).get("risk_flags") or []
    flag_txt = "  ⚠ " + "; ".join(flags) if flags else ""
    return (f'<tr><td style="padding:5px 0;border-bottom:1px solid #eee;font:13px sans-serif;color:#1b3341">'
            f'<a href="{esc(r["url"])}" style="color:#0a5960;text-decoration:none">{esc(r["title"])}</a> '
            f'— {eur(r.get("price_eur"))}'
            f'<span style="font:600 12px monospace;color:#a4402f">{esc(flag_txt)}</span></td></tr>')


def compact_list(rows, heading):
    if not rows:
        return ""
    body_rows = "".join(compact_row(r, curation.get(r["id"])) for r in rows)
    return (f'<p style="font:600 12px sans-serif;color:#6c7a82;margin:18px 0 6px">{esc(heading)} ({len(rows)})</p>'
            f'<table role="presentation" width="100%">{body_rows}</table>')


def rank_score(r):
    """Deterministic -- not from the LLM. Higher = more discount + potential signal.
    Zero for anything with no comps/drop/tag data, so it never outranks a real signal."""
    score = 0.0
    comp = comps_by_id.get(r["id"])
    if comp and not comp.get("bare_or_usufruct") and not comp.get("shared_listing") \
            and not comp.get("low_price_outlier") and not comp.get("high_price_outlier"):
        score += max(0.0, -comp["vs_median_pct"])
    drop = drops_by_id.get(r["id"])
    if drop:
        score += drop.get("drop_pct") or 0
        if drop.get("multi_cut"):
            score += 15
    curated = curation.get(r["id"]) if curation else None
    if curated:
        for tag in curated.get("potential_tags") or []:
            score += POTENTIAL_WEIGHTS.get(tag, 0)
    return score


def is_clean(rid):
    c = curation.get(rid)
    return bool(c) and not c.get("risk_flags")


if curation is None:
    main_html = "".join(card(r) for r in rows)
    top_count = 0
else:
    qualifying = [r for r in rows if is_clean(r["id"]) and rank_score(r) > 0]
    qualifying.sort(key=rank_score, reverse=True)
    top_picks = qualifying[:TOP_N]
    top_count = len(top_picks)
    if top_picks:
        top_ids = {r["id"] for r in top_picks}
        rest = [r for r in rows if r["id"] not in top_ids]
        top_html = "".join(card(r, curation.get(r["id"])) for r in top_picks)
        main_html = (f'<p style="font:600 13px sans-serif;color:#12232e;margin:0 0 8px">🎯 Top {top_count} of the day</p>'
                     f'{top_html}{compact_list(rest, "Also new — no strong signal, or a flag noted")}')
    else:
        main_html = compact_list(rows, "New — no strong signal, or a flag noted")

label = "propert" + ("y" if len(rows) == 1 else "ies") + " with a price cut" if is_drop_digest else \
        "new auction listing" + ("" if len(rows) == 1 else "s")
subject = f"[Auctions] {len(rows)} {label}" + (f" · top {top_count} of the day" if top_count else "")
disclaimer = ("Notes above are drafted from each listing's own text and are not legal or financial advice. "
              if curation is not None else "")
body = f"""<div style="max-width:640px;margin:auto;font-family:sans-serif">
<h2 style="font-family:Georgia,serif;color:#12232e">{len(rows)} {label}</h2>
<p style="color:#6c7a82;font-size:13px">Scan {meta.get('last_run','')} · source eauction24.gr ·
<a href="{esc(dashboard_link)}" style="color:#0a5960">view &amp; filter on the dashboard →</a></p>
{main_html}
<p style="color:#a4402f;font-size:12px;margin-top:18px">{disclaimer}Verify on eauction.gr + legal/engineer title check before bidding.</p>
</div>"""

msg = MIMEText(body, "html", "utf-8")
msg["Subject"] = subject
msg["From"] = os.environ["SMTP_USER"]
msg["To"] = os.environ["MAIL_TO"]
with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
    s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
print(f"emailed {len(rows)} listings to {os.environ['MAIL_TO']}")
