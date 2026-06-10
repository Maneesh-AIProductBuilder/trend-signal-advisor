import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
import json
import os
import requests
from serpapi import GoogleSearch
from dotenv import load_dotenv
import anthropic

load_dotenv()


def get_api_key(key_name):
    try:
        return st.secrets[key_name]
    except Exception:
        return os.getenv(key_name, "")


SERPAPI_KEY   = get_api_key("SERPAPI_KEY")
SERPER_KEY    = get_api_key("SERPER_API_KEY")
ANTHROPIC_KEY = get_api_key("ANTHROPIC_API_KEY")

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample_outputs")

DEMO_FILE_MAP = {
    "co-ord set":    "coord_set.json",
    "Anarkali Kurti": "Anarkali_kurti.json",
    "cape kurti":    "cape_kurti.json",
}


# ── Google Trends signal (SerpApi + keyword broadening) ───────────────────────
def get_google_trends_signal(keyword):
    cache_key = f"trends_serpapi_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        cached = st.session_state[cache_key]
        cached["from_cache"] = True
        return cached

    try:
        if not SERPAPI_KEY:
            raise ValueError("SERPAPI_KEY not configured")

        def _fetch_values(kw):
            res = GoogleSearch({
                "engine": "google_trends",
                "q": kw,
                "geo": "IN",
                "date": "today 3-m",
                "data_type": "TIMESERIES",
                "api_key": SERPAPI_KEY,
            }).get_dict()
            timeline = res.get("interest_over_time", {}).get("timeline_data", [])
            vals = []
            for week in timeline:
                wv = week.get("values", [])
                if wv:
                    vals.append(int(wv[0].get("extracted_value", 0)))
            return vals

        values = _fetch_values(keyword)

        actual_keyword_used = keyword
        broadened = False

        # Broaden if: (a) no data returned at all, or (b) all values near-zero
        should_broaden = (not values or len(values) < 4 or all(v <= 10 for v in values))
        if should_broaden and " " in keyword:
            words = keyword.strip().split()
            broader_keyword = " ".join(words[:-1]) if len(words) >= 3 else words[0]
            try:
                broader_values = _fetch_values(broader_keyword)
                if broader_values and max(broader_values) > 10:
                    values = broader_values
                    actual_keyword_used = broader_keyword
                    broadened = True
            except Exception:
                pass

        if not values or len(values) < 4:
            raise ValueError("Insufficient trend data returned for this keyword in India")

        midpoint        = len(values) // 2
        first_half_avg  = sum(values[:midpoint]) / midpoint
        second_half_avg = sum(values[midpoint:]) / (len(values) - midpoint)
        latest_value    = values[-1]
        peak_value      = max(values)
        diff            = second_half_avg - first_half_avg

        if diff > 10:
            direction, badge_class, badge_text = "rising",  "badge-up",   "↑ Rising"
        elif diff < -10:
            direction, badge_class, badge_text = "falling", "badge-down", "↓ Falling"
        else:
            direction, badge_class, badge_text = "flat",    "badge-flat", "→ Flat"

        if broadened:
            evidence = (
                f"Low direct signal for '{keyword}' — broadened to '{actual_keyword_used}': "
                f"Interest {latest_value}/100 · {direction} trend · geo: IN · 90 days"
            )
        else:
            evidence = (
                f"Interest: {latest_value}/100 now vs {int(first_half_avg)}/100 six weeks ago · "
                f"Peak: {peak_value}/100 · geo: IN · 90 days"
            )

        result = {
            "status": "success",
            "direction": direction,
            "badge_class": badge_class,
            "badge_text": badge_text,
            "evidence": evidence,
            "actual_keyword": actual_keyword_used,
            "broadened": broadened,
            "fetched_at": datetime.now().strftime("%d %b %Y %H:%M"),
            "from_cache": False,
        }
        st.session_state[cache_key] = result
        return result

    except Exception as e:
        return {
            "status": "unavailable",
            "direction": "unknown",
            "badge_class": "badge-na",
            "badge_text": "— Unavailable",
            "evidence": f"Google Trends signal unavailable — {str(e)[:80]}",
            "actual_keyword": keyword,
            "broadened": False,
            "fetched_at": "N/A",
            "from_cache": False,
        }


# ── Marketplace signal (Serper — Myntra/Meesho) ───────────────────────────────
def get_marketplace_signal(keyword):
    cache_key = f"marketplace_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    _unavailable = {
        "status": "unavailable", "strength": "unknown",
        "badge_class": "badge-na", "badge_text": "— Unavailable",
        "evidence": "Marketplace search unavailable", "fetched_at": "N/A",
    }
    try:
        if not SERPER_KEY:
            raise ValueError("SERPER_API_KEY not configured")

        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": f"{keyword} site:myntra.com OR site:meesho.com", "num": 10, "gl": "in"},
            timeout=10,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic", [])
        count   = len(organic)
        positive_kws = ["new", "just launched", "trending", "new arrival", "bestseller", "out of stock"]
        found = set()
        for item in organic:
            text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
            for kw in positive_kws:
                if kw in text:
                    found.add(kw)

        if count >= 5 and len(found) >= 2:
            strength, badge_class, badge_text = "strong",   "badge-up",   "↑ Strong"
        elif count >= 3 and len(found) >= 1:
            strength, badge_class, badge_text = "moderate", "badge-flat", "→ Moderate"
        else:
            strength, badge_class, badge_text = "weak",     "badge-down", "↓ Weak"

        evidence = (
            f"Top results from Myntra/Meesho search · {count} results · "
            f"keywords: {', '.join(sorted(found)) if found else 'none'}"
        )
        result = {
            "status": "success", "strength": strength,
            "badge_class": badge_class, "badge_text": badge_text,
            "evidence": evidence, "fetched_at": datetime.now().strftime("%d %b %Y %H:%M"),
        }
        st.session_state[cache_key] = result
        return result

    except Exception as e:
        _unavailable["evidence"] = f"Marketplace search unavailable — {str(e)[:80]}"
        return _unavailable


# ── Web social signal (Serper) ────────────────────────────────────────────────
def get_social_signal(keyword):
    cache_key = f"social_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    _unavailable = {
        "status": "unavailable", "strength": "unknown",
        "badge_class": "badge-na", "badge_text": "— Unavailable",
        "evidence": "Social search unavailable", "fetched_at": "N/A",
    }
    try:
        if not SERPER_KEY:
            raise ValueError("SERPER_API_KEY not configured")

        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            json={"q": f"{keyword} Indian fashion Instagram reels", "num": 10, "gl": "in"},
            timeout=10,
        )
        resp.raise_for_status()
        organic = resp.json().get("organic", [])
        count   = len(organic)
        social_kws = ["viral", "trending", "creator", "influencer", "reel", "views", "fashion"]
        found = set()
        for item in organic:
            text = (item.get("title", "") + " " + item.get("snippet", "")).lower()
            for kw in social_kws:
                if kw in text:
                    found.add(kw)

        has_viral = "viral" in found or "trending" in found
        if count >= 4 and has_viral:
            strength, badge_class, badge_text = "strong",   "badge-up",   "↑ Strong"
        elif count >= 3 and len(found) >= 1:
            strength, badge_class, badge_text = "moderate", "badge-flat", "→ Moderate"
        else:
            strength, badge_class, badge_text = "weak",     "badge-down", "↓ Weak"

        result = {
            "status": "success", "strength": strength,
            "badge_class": badge_class, "badge_text": badge_text,
            "evidence": (
                f"Web-indexed social mentions · {count} results · "
                f"Note: search results about social content, not direct Instagram data"
            ),
            "fetched_at": datetime.now().strftime("%d %b %Y %H:%M"),
        }
        st.session_state[cache_key] = result
        return result

    except Exception as e:
        _unavailable["evidence"] = f"Social search unavailable — {str(e)[:80]}"
        return _unavailable


# ── Claude synthesis ───────────────────────────────────────────────────────────
def synthesize_with_claude(keyword, trends_result, marketplace_result, social_result):
    cache_key = f"claude_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    _safe_defaults = {
        "india_fit": {
            "price_band": "Partial",          "price_band_reason": "Unable to assess — Claude synthesis unavailable.",
            "climate_fit": "Partial",          "climate_fit_reason": "Unable to assess — Claude synthesis unavailable.",
            "occasion_fit": "unknown",
            "cultural_fit": "Partial",         "cultural_fit_reason": "Unable to assess — Claude synthesis unavailable.",
            "value_fashion_fit": "Partial",    "value_fashion_fit_reason": "Unable to assess — Claude synthesis unavailable.",
        },
        "convergence_summary": "Signal synthesis unavailable — check individual signals above.",
        "bet_reasoning": "Claude synthesis unavailable. Use signal rows above to form your own view.",
        "skepticism_flag": "Claude synthesis unavailable — apply your own skepticism to these signals.",
        "error": True,
    }
    try:
        if not ANTHROPIC_KEY:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        user_prompt = f"""
Trend keyword: {keyword}
Category: Indian womenswear — kurtis and co-ord sets
Retailer type: Value fashion (₹399–₹1,499 price band)

SIGNAL RESULTS (these are FACTS from independent sources — do not ignore any):
1. Google Trends India (90 days, geo=IN): {trends_result['direction']} — {trends_result['evidence']}
2. Myntra/Meesho marketplace search: {marketplace_result['strength']} — {marketplace_result['evidence']}
3. Web social signal (search-indexed, NOT direct Instagram): {social_result['strength']} — {social_result['evidence']}

Please respond with ONLY a JSON object and nothing else. No preamble, no explanation outside the JSON:

{{
  "india_fit": {{
    "price_band": "Fits / Partial / Does not fit",
    "price_band_reason": "one sentence",
    "climate_fit": "Yes / Partial / No",
    "climate_fit_reason": "one sentence about Indian heat/monsoon suitability",
    "occasion_fit": "list as comma-separated string e.g. casual, ethnic, college, festive",
    "cultural_fit": "Yes / Partial / No",
    "cultural_fit_reason": "one sentence about modesty norms and cultural acceptance",
    "value_fashion_fit": "Yes / Partial / No",
    "value_fashion_fit_reason": "one sentence about whether Vishal Mega Mart or Meesho customer would buy this"
  }},
  "convergence_summary": "one sentence describing what the signals collectively tell us",
  "bet_reasoning": "2 sentences explaining the recommendation, citing specific evidence from the signals",
  "skepticism_flag": "one very specific sentence about where THIS SPECIFIC trend's signal could be misleading — not generic advice"
}}
"""
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=(
                "You are an assistant helping an Indian value-fashion category buyer evaluate a trend. "
                "The buyer works with womenswear (kurtis, co-ord sets) at a value-fashion retailer in India, "
                "selling at ₹399–₹1,499. Be honest about uncertainty. Never be overconfident. "
                "Always flag where signals could be misleading."
            ),
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)
        result["error"] = False
        st.session_state[cache_key] = result
        return result

    except json.JSONDecodeError:
        _safe_defaults["bet_reasoning"] = "Claude returned an unparseable response. Use signal rows above to form your own view."
        return _safe_defaults
    except Exception as e:
        _safe_defaults["bet_reasoning"] = f"Claude synthesis error: {str(e)[:120]}"
        return _safe_defaults


# ── Convergence scoring (deterministic) ───────────────────────────────────────
def compute_convergence(gt, mkt, soc):
    trends_score = 1.0 if gt.get("direction") == "rising" else 0.0
    mkt_str      = mkt.get("strength", "")
    market_score = 1.0 if mkt_str == "strong" else (0.5 if mkt_str == "moderate" else 0.0)
    soc_str      = soc.get("strength", "")
    social_score = 1.0 if soc_str == "strong" else (0.5 if soc_str == "moderate" else 0.0)
    total   = trends_score + market_score + social_score
    display = f"{int(total) if total == int(total) else total} / 3"
    return total, display


# ── Bet sizing (deterministic) ─────────────────────────────────────────────────
def compute_bet(convergence_total, india_fit):
    india_fit_positives = sum([
        india_fit.get("price_band") == "Fits",
        india_fit.get("climate_fit") == "Yes",
        india_fit.get("cultural_fit") == "Yes",
        india_fit.get("value_fashion_fit") == "Yes",
        bool(india_fit.get("occasion_fit", "")),
    ])
    if convergence_total >= 2.5 and india_fit_positives >= 4:
        return {"bet": "Deeper buy",                              "bet_class": "deeper",      "desc_prefix": "Strong multi-source signal with good India-fit."}
    elif convergence_total >= 1.5 and india_fit_positives >= 3:
        return {"bet": "Trial buy — watch 4-week sell-through",   "bet_class": "",            "desc_prefix": "Moderate signal with reasonable India-fit."}
    elif convergence_total >= 1.0 and india_fit_positives >= 2:
        return {"bet": "Small trial only — high uncertainty",     "bet_class": "small-trial", "desc_prefix": "Mixed signals — proceed with caution."}
    else:
        return {"bet": "Monitor only — do not buy yet",           "bet_class": "monitor",     "desc_prefix": "Insufficient signal to justify stock commitment."}


# ── India-fit badge HTML helper ────────────────────────────────────────────────
def _fit_badge(value):
    v = (value or "").lower()
    if v in ("yes", "fits"):
        return f'<span class="india-badge-yes">&#10003; {value}</span>'
    elif v == "partial":
        return f'<span class="india-badge-partial">&#9888; {value}</span>'
    else:
        return f'<span class="india-badge-no">&#10007; {value}</span>'


# ── Estimate card height from content length ───────────────────────────────────
def estimate_card_height(india_fit, syn, bet_data):
    """Base height + extra lines for long text fields."""
    base = 900
    char_per_line = 68  # approx chars per line at 13px in ~640px column

    def lines(text):
        return max(1, len(str(text)) // char_per_line + 1)

    extra = 0
    for field in ["price_band_reason", "climate_fit_reason", "cultural_fit_reason", "value_fashion_fit_reason"]:
        extra += lines(india_fit.get(field, "")) * 18

    extra += lines(syn.get("convergence_summary", "")) * 20
    extra += lines(syn.get("bet_reasoning", "")) * 20
    extra += lines(syn.get("skepticism_flag", "")) * 20
    extra += lines(bet_data.get("desc_prefix", "")) * 20

    return base + extra


# ── Build result card HTML ─────────────────────────────────────────────────────
def build_card_html(display_kw, gt, mkt, soc, syn, convergence_display, india_fit, bet_data):
    bet_class_attr = f' {bet_data["bet_class"]}' if bet_data["bet_class"] else ""

    price_badge    = _fit_badge(india_fit.get("price_band", "Partial"))
    climate_badge  = _fit_badge(india_fit.get("climate_fit", "Partial"))
    cultural_badge = _fit_badge(india_fit.get("cultural_fit", "Partial"))
    vf_badge       = _fit_badge(india_fit.get("value_fashion_fit", "Partial"))
    occasion_str   = india_fit.get("occasion_fit", "—")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: transparent;
    padding: 2px 0 8px;
  }}
  .result-outer-card {{
    background: #FAFAF9;
    border: 1.5px solid #D1CBC0;
    border-radius: 12px;
    overflow: visible;
  }}
  .result-card-header {{
    background: #F0EDE8;
    padding: 9px 16px;
    border-bottom: 1px solid #E0DDD7;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-radius: 12px 12px 0 0;
  }}
  .result-card-header-title {{
    font-size: 10px; font-weight: 700; color: #44403C;
    text-transform: uppercase; letter-spacing: 0.08em;
  }}
  .result-card-header-kw {{ font-size: 11px; color: #9B9590; font-style: italic; }}
  .result-section {{ padding: 14px 16px; border-bottom: 1px solid #EDE9E4; }}
  .section-eyebrow {{
    font-size: 9.5px; font-weight: 700; color: #78716C;
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 10px;
  }}

  /* Signal rows */
  .signal-row {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #F5F5F4;
  }}
  .signal-row:last-child {{ border-bottom: none; }}
  .signal-name {{ font-size: 13px; font-weight: 600; color: #1C1917; margin-bottom: 3px; }}
  .signal-evidence {{ font-size: 13px; color: #57534E; line-height: 1.45; }}

  /* Badges */
  .badge-up   {{ background: #DCFCE7; color: #14532D; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; }}
  .badge-flat {{ background: #FEF9C3; color: #713F12; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; }}
  .badge-down {{ background: #FEE2E2; color: #7F1D1D; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; }}
  .badge-na   {{ background: #F3F4F6; color: #6B7280; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; }}

  /* Convergence */
  .convergence-panel {{
    background: #F0EDE8; border: 1px solid #E0DDD7; border-radius: 8px;
    padding: 12px 14px; display: flex; align-items: center; gap: 14px;
  }}
  .convergence-score {{ font-size: 28px; font-weight: 700; color: #1C1917; flex-shrink: 0; }}
  .convergence-text  {{ font-size: 14px; color: #1C1917; line-height: 1.6; }}

  /* India-fit stacked rows */
  .india-row-stack {{
    padding: 10px 0;
    border-bottom: 1px solid #EDE9E4;
  }}
  .india-row-stack:last-child {{ border-bottom: none; }}
  .india-row-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 5px;
  }}
  .india-key {{ font-size: 13px; font-weight: 500; color: #1C1917; }}
  .india-row-reason {{ font-size: 12px; color: #57534E; line-height: 1.55; }}
  .india-occasion-val {{ font-size: 13px; color: #44403C; }}
  .india-badge-yes     {{ background: #DCFCE7; color: #14532D; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}
  .india-badge-partial {{ background: #FEF3C7; color: #92400E; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}
  .india-badge-no      {{ background: #FEE2E2; color: #7F1D1D; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}

  /* Bet block */
  .bet-section {{ padding: 0; border-bottom: none; }}
  .bet-block {{
    background: #1C1917; padding: 16px 18px;
  }}
  .bet-block.deeper      {{ background: #14532D; }}
  .bet-block.small-trial {{ background: #92400E; }}
  .bet-block.monitor     {{ background: #44403C; }}
  .bet-eyebrow {{
    font-size: 9.5px; font-weight: 700; color: #78716C;
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px;
  }}
  .bet-size-text {{ font-size: 16px; font-weight: 600; color: #F5F0EB; margin-bottom: 6px; }}
  .bet-reason-text {{ font-size: 13px; color: #D6D3D1; line-height: 1.65; }}

  /* Skepticism flag */
  .skeptic-flag {{
    background: #FFFBEB; border-top: 1px solid #FDE68A;
    padding: 14px 18px 20px; font-size: 13px; color: #78350F; line-height: 1.65;
    border-radius: 0 0 12px 12px;
  }}
  .skeptic-label {{
    font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.06em; color: #92400E; margin-bottom: 5px;
  }}
</style>
</head>
<body>

<div class="result-outer-card">

  <div class="result-card-header">
    <span class="result-card-header-title">Analysis result</span>
    <span class="result-card-header-kw">{display_kw}</span>
  </div>

  <!-- Section 1: Signal sources -->
  <div class="result-section">
    <div class="section-eyebrow">Signal sources</div>

    <div class="signal-row">
      <div>
        <div class="signal-name">Google Trends India</div>
        <div class="signal-evidence">{gt["evidence"]}</div>
      </div>
      <span class="{gt["badge_class"]}">{gt["badge_text"]}</span>
    </div>

    <div class="signal-row">
      <div>
        <div class="signal-name">Myntra / Meesho catalog</div>
        <div class="signal-evidence">{mkt["evidence"]}</div>
      </div>
      <span class="{mkt["badge_class"]}">{mkt["badge_text"]}</span>
    </div>

    <div class="signal-row">
      <div>
        <div class="signal-name">Web social signal (search-indexed)</div>
        <div class="signal-evidence">{soc["evidence"]}</div>
      </div>
      <span class="{soc["badge_class"]}">{soc["badge_text"]}</span>
    </div>

  </div>

  <!-- Section 2: Convergence -->
  <div class="result-section">
    <div class="section-eyebrow">Signal convergence</div>
    <div class="convergence-panel">
      <div class="convergence-score">{convergence_display}</div>
      <div class="convergence-text">{syn.get("convergence_summary", "Signal synthesis unavailable.")}</div>
    </div>
  </div>

  <!-- Section 3: India-fit check -->
  <div class="result-section">
    <div class="section-eyebrow">India-fit check</div>

    <div class="india-row-stack">
      <div class="india-row-top">
        <span class="india-key">Price band (&#8377;399&#8211;&#8377;1,499)</span>
        {price_badge}
      </div>
      <div class="india-row-reason">{india_fit.get("price_band_reason", "")}</div>
    </div>

    <div class="india-row-stack">
      <div class="india-row-top">
        <span class="india-key">Climate fit</span>
        {climate_badge}
      </div>
      <div class="india-row-reason">{india_fit.get("climate_fit_reason", "")}</div>
    </div>

    <div class="india-row-stack">
      <div class="india-row-top">
        <span class="india-key">Occasion fit</span>
        <span class="india-occasion-val">{occasion_str}</span>
      </div>
    </div>

    <div class="india-row-stack">
      <div class="india-row-top">
        <span class="india-key">Cultural / modesty fit</span>
        {cultural_badge}
      </div>
      <div class="india-row-reason">{india_fit.get("cultural_fit_reason", "")}</div>
    </div>

    <div class="india-row-stack">
      <div class="india-row-top">
        <span class="india-key">Value-fashion buyer fit</span>
        {vf_badge}
      </div>
      <div class="india-row-reason">{india_fit.get("value_fashion_fit_reason", "")}</div>
    </div>

  </div>

  <!-- Section 4: Bet block -->
  <div class="bet-section">
    <div class="bet-block{bet_class_attr}">
      <div class="bet-eyebrow">Buying recommendation</div>
      <div class="bet-size-text">{bet_data["bet"]}</div>
      <div class="bet-reason-text">{bet_data["desc_prefix"]} {syn.get("bet_reasoning", "")}</div>
    </div>
  </div>

  <!-- Skepticism flag -->
  <div class="skeptic-flag">
    <div class="skeptic-label">&#9888; Skepticism flag</div>
    {syn.get("skepticism_flag", "Apply your own skepticism — Claude synthesis unavailable.")}
  </div>

</div>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# ── Page config ───────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Trend Signal Advisor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  #MainMenu { visibility: hidden; }
  footer    { visibility: hidden; }
  header    { visibility: hidden; }

  /* Sidebar */
  section[data-testid="stSidebar"] { background: #F7F5F0; }

  /* Timestamp line */
  .signals-timestamp {
    font-size: 11px; color: #A8A29E;
    text-align: right; margin-top: 4px; margin-bottom: 8px;
  }

  /* App header */
  .app-header {
    background: #1C1917; color: #F5F0EB;
    padding: 20px 28px; border-radius: 10px; margin-bottom: 24px;
  }
  .app-header h1 { font-size: 18px; font-weight: 600; color: #F5F0EB; margin: 0; }
  .app-header p  { font-size: 14px; color: #F5F0EB; margin: 4px 0 0; }

  /* Expander */
  .streamlit-expanderHeader {
    font-size: 12px !important; font-weight: 500 !important;
    color: #78716C !important; background: transparent !important;
    border: none !important; padding: 8px 0 !important;
  }
  .streamlit-expanderContent { border: none !important; padding: 8px 0 0 !important; }

  /* Hero */
  .hero-section { padding: 4px 0 8px; }
  .hero-headline { font-size: 20px; font-weight: 600; color: #1C1917; margin: 0 0 10px; letter-spacing: -0.01em; }
  .hero-body { font-size: 13px; color: #292524; line-height: 1.7; margin: 0 0 14px; }
  .hero-pills { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
  .hero-pill { background: #1C1917; color: #F5F0EB; font-size: 11px; font-weight: 500; padding: 4px 12px; border-radius: 20px; }
  .hero-steps { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 14px; }
  .hero-step { background: #FFFFFF; border: 1px solid #EDE9E4; border-radius: 8px; padding: 10px 12px; text-align: center; }
  .hero-step-num { font-size: 18px; font-weight: 700; color: #D1CBC0; margin-bottom: 4px; }
  .hero-step-text { font-size: 11px; color: #78716C; line-height: 1.4; }
  .hero-disclaimer { font-size: 11.5px; color: #78716C; font-style: italic; border-left: 2px solid #D1CBC0; padding-left: 10px; line-height: 1.6; }

  /* Input label */
  .input-label { font-size: 10.5px; font-weight: 600; color: #78716C; text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 6px; }

  /* Input */
  .stTextInput input { border-radius: 8px; border: 1.5px solid #E8E3DA; background: #FAF9F7; font-size: 14px; padding: 10px 14px; }
  .stTextInput input:focus { border-color: #292524; box-shadow: 0 0 0 2px rgba(41,37,36,0.08); }

  /* Button */
  .stButton button { background: #292524; color: #F5F0EB; border: none; border-radius: 8px; font-weight: 500; padding: 10px 20px; width: 100%; font-size: 14px; }

  /* Outer page card — centre column in wide layout (covers both old and new Streamlit testid names) */
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2),
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2),
  [data-testid="stHorizontalBlock"] > div:nth-child(2) {
    background: #FFFFFF !important;
    border: 1.5px solid #D1CBC0 !important;
    border-radius: 16px !important;
    padding: 28px 32px 32px !important;
    box-shadow: 0 2px 16px rgba(28,25,23,0.07) !important;
    margin-top: 16px !important;
  }
</style>
""", unsafe_allow_html=True)


# ── Sidebar demo loader ────────────────────────────────────────────────────────
st.sidebar.markdown("### Try a demo")
demo_choice = st.sidebar.selectbox(
    "Load a sample analysis:",
    ["— select —", "co-ord set", "Anarkali Kurti", "cape kurti"],
    label_visibility="collapsed",
)


# ── Centred content column ─────────────────────────────────────────────────────
_, col, _ = st.columns([1, 3, 1])

with col:

    # Header
    st.markdown("""
<div class="app-header">
  <h1>📊 Trend Signal Advisor</h1>
  <p>India womenswear &nbsp;·&nbsp; Value fashion &nbsp;·&nbsp; Early signal intelligence</p>
</div>
""", unsafe_allow_html=True)

    # Onboarding hero expander
    with st.expander("What is this tool? ↓", expanded=False):
        st.markdown("""
<div class="hero-section">
  <div class="hero-headline">Is this trend worth a bet?</div>
  <div class="hero-body">
    For category buyers at value-fashion retailers. By the time a trend appears in your
    sales data, the buying window is already gone. This tool checks early evidence from
    3 independent sources — before demand is obvious.
  </div>
  <div class="hero-pills">
    <span class="hero-pill">Google Trends India</span>
    <span class="hero-pill">Myntra / Meesho catalog</span>
    <span class="hero-pill">Web social signal</span>
  </div>
  <div class="hero-steps">
    <div class="hero-step"><div class="hero-step-num">01</div><div class="hero-step-text">Enter a trend keyword</div></div>
    <div class="hero-step"><div class="hero-step-num">02</div><div class="hero-step-text">3 sources vote independently</div></div>
    <div class="hero-step"><div class="hero-step-num">03</div><div class="hero-step-text">Get a defensible recommendation</div></div>
  </div>
  <div class="hero-disclaimer">
    This tool helps you reason through uncertainty — not decide for you.
    Always apply your store-floor knowledge alongside the signal.
  </div>
</div>
""", unsafe_allow_html=True)

    # Input
    st.markdown('<div class="input-label" style="margin-top:16px;">Enter a trend keyword</div>', unsafe_allow_html=True)
    keyword = st.text_input(
        "",
        placeholder='e.g. "mirror embroidery kurti", "coord set womenswear"',
        label_visibility="collapsed",
    )
    analyse = st.button("Analyse trend →", use_container_width=True)

    # ── Demo mode ─────────────────────────────────────────────────────────────
    if demo_choice != "— select —":
        fname = DEMO_FILE_MAP.get(demo_choice)
        fpath = os.path.join(SAMPLE_DIR, fname) if fname else None
        if fpath and os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                demo = json.load(f)

            st.info(f"📁 Demo mode — loaded from cached analysis · {demo.get('analysed_at', 'unknown')}")

            gt_d   = demo["trends_result"]
            mkt_d  = demo["marketplace_result"]
            soc_d  = demo["social_result"]
            syn_d  = demo["claude_synthesis"]
            india_fit_d  = syn_d.get("india_fit", {})
            conv_total_d = demo.get("convergence_total", 0)
            conv_disp_d  = f"{int(conv_total_d) if conv_total_d == int(conv_total_d) else conv_total_d} / 3"
            bet_d        = compute_bet(conv_total_d, india_fit_d)

            demo_card = build_card_html(
                demo["keyword"], gt_d, mkt_d, soc_d, syn_d,
                conv_disp_d, india_fit_d, bet_d,
            )
            components.html(demo_card, height=estimate_card_height(india_fit_d, syn_d, bet_d), scrolling=False)
            st.markdown(
                f'<div class="signals-timestamp">Signals fetched: {gt_d.get("fetched_at", "N/A")}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning(f"Demo file not found for '{demo_choice}'. Run the analysis once to generate it.")

    # ── Live analysis ──────────────────────────────────────────────────────────
    if analyse:
        kw = keyword.strip()
        if not kw:
            st.warning("Please enter a trend keyword before analysing.")
            st.stop()

        with st.spinner("Fetching signals and synthesising with Claude…"):
            gt  = get_google_trends_signal(kw)
            mkt = get_marketplace_signal(kw)
            soc = get_social_signal(kw)
            syn = synthesize_with_claude(kw, gt, mkt, soc)

        convergence_total, convergence_display = compute_convergence(gt, mkt, soc)
        india_fit = syn.get("india_fit", {})
        bet_data  = compute_bet(convergence_total, india_fit)

        card = build_card_html(kw, gt, mkt, soc, syn, convergence_display, india_fit, bet_data)
        components.html(card, height=estimate_card_height(india_fit, syn, bet_data), scrolling=False)

        ts = gt.get("fetched_at", "N/A")
        st.markdown(
            f'<div class="signals-timestamp">Signals fetched: {ts}</div>',
            unsafe_allow_html=True,
        )

        # Auto-save to sample_outputs if keyword matches a demo slot
        fname = DEMO_FILE_MAP.get(kw) or DEMO_FILE_MAP.get(kw.title())
        if fname:
            os.makedirs(SAMPLE_DIR, exist_ok=True)
            payload = {
                "keyword": kw,
                "analysed_at": datetime.now().strftime("%d %b %Y %H:%M"),
                "trends_result": gt,
                "marketplace_result": mkt,
                "social_result": soc,
                "claude_synthesis": syn,
                "convergence_total": convergence_total,
                "bet": bet_data["bet"],
                "bet_class": bet_data["bet_class"],
            }
            with open(os.path.join(SAMPLE_DIR, fname), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    # ── About these signals expander ───────────────────────────────────────────
    with st.expander("About these signals ↓", expanded=False):
        st.markdown("""
**Google Trends India**
Reflects relative search interest in India over the past 90 days, not absolute volume. A score of 100 means peak popularity in the period — not "100 searches." A flat or falling score does not mean the trend is dead; it may already be mainstream. Niche or regional spellings can score near zero even if the product sells well. *When a compound keyword scores near-zero, the tool automatically retries with a broader keyword.*

---

**Myntra / Meesho catalog (via web search)**
Searches Google's index of Myntra and Meesho product pages. Results reflect what Google has indexed, not the live catalog. "New" and "trending" keywords appear in seller titles and snippets — they are self-reported by sellers and may be aspirational, not accurate. Out-of-stock signals can mean high demand or poor replenishment; they are ambiguous without sell-through data.

---

**Web social signal (search-indexed)**
Searches Google for pages that discuss this trend alongside Instagram, reels, and influencer content. This is NOT direct Instagram data — Instagram blocks search engines. A "strong" score means more web articles and blogs are writing about the trend, not that the reels themselves have high views. Content farms and trend-aggregator sites can inflate this score.

---

**Claude synthesis (India-fit + bet reasoning)**
Claude reads the three signal results and applies fashion-retail context to assess India fit and recommend a bet size. It can misread ambiguous evidence or hallucinate context it doesn't have. The bet size itself is calculated deterministically from the scores — Claude only explains the reasoning, it does not set the recommendation.
""")
