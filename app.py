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
    "co-ord set":     "coord_set.json",
    "Anarkali Kurti": "Anarkali_kurti.json",
    "cape kurti":     "cape_kurti.json",
}

WEIGHT_TRENDS = 1.5
WEIGHT_MARKET = 1.0
WEIGHT_SOCIAL = 0.5
WEIGHT_NEWS   = 0.75
MAX_SCORE     = 4.5


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


# ── Marketplace signal (Serper — Myntra/Meesho, 2-query: catalog + discounts) ─
def get_marketplace_signal(keyword):
    cache_key = f"marketplace_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        return {**st.session_state[cache_key], "from_cache": True}

    try:
        if not SERPER_KEY:
            raise ValueError("SERPER_API_KEY not configured")

        headers = {"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"}

        # Query 1 — catalog presence
        cat_resp = requests.post(
            "https://google.serper.dev/search",
            json={"q": f"{keyword} site:myntra.com OR site:meesho.com", "num": 10, "gl": "in"},
            headers=headers, timeout=10,
        )
        cat_resp.raise_for_status()
        catalog_results = cat_resp.json().get("organic", [])
        catalog_count   = len(catalog_results)

        cat_text = " ".join(
            str(r.get("title", "")) + " " + str(r.get("snippet", ""))
            for r in catalog_results
        ).lower()
        launch_keywords = ["new", "just launched", "new arrival", "trending", "bestseller", "new launch"]
        launch_hits = sum(1 for w in launch_keywords if w in cat_text)

        # Query 2 — discount / price pressure
        disc_resp = requests.post(
            "https://google.serper.dev/search",
            json={
                "q": (f"{keyword} "
                      f"(\"% off\" OR \"sale\" OR \"discount\" OR \"clearance\" OR \"flat off\") "
                      f"site:meesho.com OR site:myntra.com"),
                "num": 10, "gl": "in",
            },
            headers=headers, timeout=10,
        )
        disc_resp.raise_for_status()
        discount_results = disc_resp.json().get("organic", [])
        discount_count   = len(discount_results)

        disc_text = " ".join(
            str(r.get("title", "")) + " " + str(r.get("snippet", ""))
            for r in discount_results
        ).lower()
        discount_keywords = ["% off", "flat off", "sale", "clearance", "discount", "upto", "up to", "under ₹"]
        discount_hits = sum(1 for w in discount_keywords if w in disc_text)

        # Interpret combined signal
        if catalog_count >= 5 and launch_hits >= 2 and discount_hits <= 2:
            strength      = "strong"
            badge_class   = "badge-up"
            badge_text    = "↑ Strong — new listings, healthy pricing"
            market_health = "healthy"
            evidence      = (f"{catalog_count} listings · "
                             f"{launch_hits} new/launch signals · "
                             f"minimal discounting detected")
        elif catalog_count >= 3 and discount_hits >= 4:
            strength      = "oversupply"
            badge_class   = "badge-flat"
            badge_text    = "⚠ Listed but heavily discounted"
            market_health = "oversupply"
            evidence      = (f"{catalog_count} listings BUT "
                             f"{discount_hits} discount signals — "
                             f"possible oversupply or slow sell-through")
        elif catalog_count >= 3:
            strength      = "moderate"
            badge_class   = "badge-flat"
            badge_text    = "→ Moderate catalog presence"
            market_health = "moderate"
            evidence      = (f"{catalog_count} listings · "
                             f"{launch_hits} launch signals · "
                             f"{discount_hits} discount signals")
        elif catalog_count >= 1:
            strength      = "weak"
            badge_class   = "badge-down"
            badge_text    = "↓ Sparse catalog presence"
            market_health = "weak"
            evidence      = (f"Only {catalog_count} listings found · "
                             f"not yet mainstream in marketplace")
        else:
            strength      = "none"
            badge_class   = "badge-na"
            badge_text    = "— Not found in marketplace"
            market_health = "none"
            evidence      = ("No Myntra/Meesho listings found — "
                             "very early stage or keyword mismatch")

        result = {
            "status": "success",
            "strength": strength,
            "badge_class": badge_class,
            "badge_text": badge_text,
            "evidence": evidence,
            "market_health": market_health,
            "catalog_count": catalog_count,
            "discount_hits": discount_hits,
            "fetched_at": datetime.now().strftime("%d %b %Y %H:%M"),
            "from_cache": False,
        }
        st.session_state[cache_key] = result
        return result

    except Exception as e:
        return {
            "status": "unavailable",
            "strength": "unknown",
            "badge_class": "badge-na",
            "badge_text": "— Unavailable",
            "evidence": f"Marketplace signal unavailable: {str(e)[:60]}",
            "market_health": "unknown",
            "catalog_count": 0,
            "discount_hits": 0,
            "fetched_at": "N/A",
            "from_cache": False,
        }


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


# ── News coverage signal (Serper /news endpoint) ──────────────────────────────
def get_news_signal(keyword):
    cache_key = f"serper_news_{keyword.lower().strip()}"
    if cache_key in st.session_state:
        return {**st.session_state[cache_key], "from_cache": True}

    try:
        if not SERPER_KEY:
            raise ValueError("SERPER_API_KEY not configured")

        response = requests.post(
            "https://google.serper.dev/news",
            json={"q": f"{keyword} fashion india", "gl": "in", "num": 10},
            headers={"X-API-KEY": SERPER_KEY, "Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        articles = response.json().get("news", [])
        article_count = len(articles)

        positive_words = [
            "trending", "popular", "demand", "launch", "season", "style",
            "rising", "fashion", "must-have", "bestseller", "kurti",
            "ethnic", "meesho", "myntra", "new collection",
        ]
        all_text = " ".join(
            str(a.get("title", "")) + " " + str(a.get("snippet", ""))
            for a in articles
        ).lower()
        positive_hits = sum(1 for w in positive_words if w in all_text)
        top_headlines = [a.get("title", "") for a in articles[:2] if a.get("title")]

        if article_count >= 3 and positive_hits >= 2:
            badge_class, badge_text = "badge-up",   "↑ Active coverage"
        elif article_count >= 1:
            badge_class, badge_text = "badge-flat", "→ Some coverage"
        else:
            badge_class, badge_text = "badge-na",   "— No news found"

        result = {
            "status": "success",
            "badge_class": badge_class,
            "badge_text": badge_text,
            "evidence": (f"{article_count} news articles · "
                         f"{positive_hits} fashion-relevant signals"),
            "article_count": article_count,
            "top_headlines": top_headlines,
            "fetched_at": datetime.now().strftime("%d %b %Y %H:%M"),
            "from_cache": False,
        }
        st.session_state[cache_key] = result
        return result

    except Exception as e:
        return {
            "status": "unavailable",
            "badge_class": "badge-na",
            "badge_text": "— Unavailable",
            "evidence": f"News signal unavailable: {str(e)[:60]}",
            "article_count": 0,
            "top_headlines": [],
            "fetched_at": "N/A",
            "from_cache": False,
        }


# ── Weighted convergence scoring ──────────────────────────────────────────────
def score_signal(value):
    s = str(value).lower()
    if "oversupply" in s or "heavily discounted" in s:
        return 0.25
    if any(t in s for t in [
        "rising", "strong", "active", "↑", "healthy pricing",
        "active coverage", "active discussion",
    ]):
        return 1.0
    if any(t in s for t in [
        "flat", "moderate", "some", "→", "sparse", "mentions", "coverage",
    ]):
        return 0.5
    return 0.0


def compute_convergence(gt, mkt, soc, news=None):
    trends_raw = score_signal(gt.get("direction", ""))
    market_raw = score_signal(mkt.get("badge_text", ""))
    social_raw = score_signal(soc.get("strength", ""))
    news_raw   = score_signal(news.get("badge_text", "") if news else "")

    weighted_score = (
        trends_raw * WEIGHT_TRENDS +
        market_raw * WEIGHT_MARKET +
        social_raw * WEIGHT_SOCIAL +
        news_raw   * WEIGHT_NEWS
    )
    demand_score = trends_raw * WEIGHT_TRENDS + market_raw * WEIGHT_MARKET
    buzz_score   = social_raw * WEIGHT_SOCIAL + news_raw   * WEIGHT_NEWS

    return {
        "weighted_score": weighted_score,
        "demand_score":   demand_score,
        "buzz_score":     buzz_score,
        "trends_raw":     trends_raw,
        "market_raw":     market_raw,
        "social_raw":     social_raw,
        "news_raw":       news_raw,
        "display":        f"{weighted_score:.1f} / {MAX_SCORE}",
    }


# ── India-fit positives count ─────────────────────────────────────────────────
def count_india_fit_positives(india_fit):
    return sum(
        1 for v in [
            india_fit.get("price_band", ""),
            india_fit.get("climate_fit", ""),
            india_fit.get("cultural_fit", ""),
            india_fit.get("value_fashion_fit", ""),
        ]
        if any(p in str(v) for p in ["Fits", "Yes"])
    )


# ── Bet sizing with override rules ────────────────────────────────────────────
def compute_bet(scores, marketplace_result, india_fit, india_fit_positives):
    weighted_score  = scores["weighted_score"]
    trends_raw      = scores["trends_raw"]
    market_raw      = scores["market_raw"]
    buzz_score      = scores["buzz_score"]

    demand_weak     = (trends_raw <= 0.5 and market_raw <= 0.5)
    buzz_active     = (buzz_score >= 1.0)
    oversupply_flag = (marketplace_result.get("market_health", "") == "oversupply")
    hard_india_fail = (
        "Does not fit" in india_fit.get("price_band", "") or
        india_fit.get("climate_fit", "").strip() == "No"
    )

    bet_override = None

    if hard_india_fail:
        bet       = "Do not buy — India-fit failure"
        bet_class = "monitor"
        bet_override = ("Hard stop: this trend fails India price band "
                        "or climate fit — signal strength is irrelevant.")

    elif oversupply_flag and trends_raw <= 0.5:
        bet       = "Do not buy — marketplace oversupply"
        bet_class = "monitor"
        bet_override = ("Override: heavy discounting detected on "
                        "Myntra/Meesho combined with weak search demand. "
                        "Suppliers are likely liquidating unsold stock — "
                        "not a rising trend.")

    elif demand_weak and buzz_active:
        bet       = "Monitor only — buzz without demand"
        bet_class = "monitor"
        bet_override = ("Override: demand signals are weak despite active "
                        "editorial/social buzz. Social buzz may not convert "
                        "to value-fashion sales. Watch 4 weeks before "
                        "any commitment.")

    elif weighted_score >= 3.5 and india_fit_positives >= 4:
        bet       = "Deeper buy — strong convergent signal"
        bet_class = "deeper"

    elif weighted_score >= 2.5 and india_fit_positives >= 3:
        bet       = "Trial buy — watch 4-week sell-through"
        bet_class = ""

    elif weighted_score >= 1.5 and india_fit_positives >= 2:
        bet       = "Small trial only — high uncertainty"
        bet_class = "small-trial"

    elif weighted_score >= 0.75:
        bet       = "Monitor only — insufficient signal"
        bet_class = "monitor"

    else:
        bet       = "Do not buy — no meaningful signal"
        bet_class = "monitor"

    return {
        "bet":          bet,
        "bet_class":    bet_class,
        "bet_override": bet_override,
        "desc_prefix":  "",
    }


# ── Claude synthesis ───────────────────────────────────────────────────────────
def synthesize_with_claude(keyword, trends_result, marketplace_result, social_result, news_result, scores):
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
        "signal_agreement": "Signal synthesis unavailable.",
        "disagreement_note": None,
        "bet_reasoning": "Claude synthesis unavailable. Use signal rows above to form your own view.",
        "skepticism_flag": "Claude synthesis unavailable — apply your own skepticism to these signals.",
        "error": True,
    }
    try:
        if not ANTHROPIC_KEY:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

        top_headlines = news_result.get("top_headlines", []) if news_result else []
        news_badge    = news_result.get("badge_text", "N/A") if news_result else "N/A"
        news_evidence = news_result.get("evidence", "N/A") if news_result else "N/A"

        user_prompt = f"""Trend: {keyword}
Category: Indian womenswear — kurtis and co-ord sets
Retailer: Value fashion, ₹399–₹1,499, Tier 1–3 India

DEMAND SIGNALS (weighted higher — more reliable for buying decisions):
1. Google Trends India [weight 1.5x]: {trends_result['direction']} — {trends_result['evidence']}
2. Myntra/Meesho marketplace [weight 1.0x]: {marketplace_result['badge_text']} — {marketplace_result['evidence']}
   Market health: {marketplace_result.get('market_health','unknown')} | Discount signals: {marketplace_result.get('discount_hits', 0)}

EDITORIAL/BUZZ SIGNALS (weighted lower — may not convert to sales):
3. Web social signal — indexed Instagram [weight 0.5x]: {social_result['strength']} — {social_result['evidence']}
4. Google News India [weight 0.75x]: {news_badge} — {news_evidence}
   Top headlines: {top_headlines}

Weighted score: {scores['weighted_score']:.1f} / {MAX_SCORE}
Demand group: {scores['demand_score']:.1f} / 2.5 | Buzz/editorial group: {scores['buzz_score']:.1f} / 2.0
Override applied: None

Please respond with ONLY a JSON object and nothing else:

{{
  "india_fit": {{
    "price_band": "Fits / Partial / Does not fit",
    "price_band_reason": "one sentence",
    "climate_fit": "Yes / Partial / No",
    "climate_fit_reason": "one sentence about Indian heat/monsoon suitability",
    "occasion_fit": "comma-separated e.g. casual, ethnic, college, festive",
    "cultural_fit": "Yes / Partial / No",
    "cultural_fit_reason": "one sentence about modesty norms and cultural acceptance",
    "value_fashion_fit": "Yes / Partial / No",
    "value_fashion_fit_reason": "one sentence about whether Meesho or Vishal Mega Mart customer would buy this"
  }},
  "convergence_summary": "one sentence describing what the signals collectively tell us",
  "signal_agreement": "one sentence — do demand and buzz signals agree or conflict?",
  "disagreement_note": "if demand and buzz conflict: what specific evidence would resolve this — else null",
  "bet_reasoning": "2 sentences explaining the recommendation, citing specific signal evidence",
  "skepticism_flag": "one very specific sentence about where THIS trend's signal could be misleading"
}}"""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
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


# ── India-fit badge HTML helper ────────────────────────────────────────────────
def _fit_badge(value):
    v = (value or "").lower()
    if v in ("yes", "fits"):
        return f'<span class="india-badge-yes">&#10003; {value}</span>'
    elif v == "partial":
        return f'<span class="india-badge-partial">&#9888; {value}</span>'
    else:
        return f'<span class="india-badge-no">&#10007; {value}</span>'


# ── Inline signal badge helper (for convergence panel) ────────────────────────
def _inline_badge(badge_class, badge_text):
    styles = {
        "badge-up":   "background:#DCFCE7;color:#14532D",
        "badge-flat": "background:#FEF9C3;color:#713F12",
        "badge-down": "background:#FEE2E2;color:#7F1D1D",
        "badge-na":   "background:#F3F4F6;color:#6B7280",
    }
    style = styles.get(badge_class, styles["badge-na"])
    return (f'<span style="{style};font-size:10px;font-weight:600;'
            f'padding:2px 7px;border-radius:3px;white-space:nowrap;'
            f'display:inline-block;margin:1px 3px 1px 0;">'
            f'{badge_text}</span>')


# ── Estimate card height from content length ───────────────────────────────────
def estimate_card_height(india_fit, syn, bet_data, scores=None):
    base = 960 if scores is None else 1060
    char_per_line = 68

    def lines(text):
        return max(1, len(str(text)) // char_per_line + 1)

    extra = 0
    for field in ["price_band_reason", "climate_fit_reason", "cultural_fit_reason", "value_fashion_fit_reason"]:
        extra += lines(india_fit.get(field, "")) * 18

    extra += lines(syn.get("convergence_summary", "")) * 20
    extra += lines(syn.get("signal_agreement", "")) * 20
    extra += lines(syn.get("bet_reasoning", "")) * 20
    extra += lines(syn.get("skepticism_flag", "")) * 20

    if bet_data.get("bet_override"):
        extra += lines(bet_data["bet_override"]) * 20 + 30

    disagreement_note = syn.get("disagreement_note")
    if disagreement_note and str(disagreement_note).lower() not in ("null", "none", ""):
        extra += lines(disagreement_note) * 20 + 40

    return base + extra


# ── Build result card HTML ─────────────────────────────────────────────────────
def build_card_html(display_kw, gt, mkt, soc, syn, convergence_display,
                    india_fit, bet_data, news=None, scores=None):
    bet_class_attr = f' {bet_data["bet_class"]}' if bet_data["bet_class"] else ""

    _news = news or {"badge_class": "badge-na", "badge_text": "— Unavailable", "evidence": "News signal not fetched"}

    price_badge    = _fit_badge(india_fit.get("price_band", "Partial"))
    climate_badge  = _fit_badge(india_fit.get("climate_fit", "Partial"))
    cultural_badge = _fit_badge(india_fit.get("cultural_fit", "Partial"))
    vf_badge       = _fit_badge(india_fit.get("value_fashion_fit", "Partial"))
    occasion_str   = india_fit.get("occasion_fit", "—")

    # Convergence panel — new weighted layout when scores available, legacy for demos
    if scores:
        signal_agreement = syn.get("signal_agreement", syn.get("convergence_summary", ""))
        convergence_panel_html = f"""
    <div class="convergence-panel">
      <div class="convergence-score">{scores['weighted_score']:.1f}<span class="convergence-denom"> / {MAX_SCORE}</span></div>
      <div class="convergence-text">
        <div style="margin-bottom:10px;font-size:13px;line-height:1.5;">{signal_agreement}</div>
        <div class="convergence-breakdown">
          <div class="breakdown-row">
            <span class="breakdown-label">Demand</span>
            {_inline_badge(gt["badge_class"], gt["badge_text"])}
            {_inline_badge(mkt["badge_class"], mkt["badge_text"])}
          </div>
          <div class="breakdown-row">
            <span class="breakdown-label">Editorial / Buzz</span>
            {_inline_badge(soc["badge_class"], soc["badge_text"])}
            {_inline_badge(_news["badge_class"], _news["badge_text"])}
          </div>
        </div>
      </div>
    </div>"""
    else:
        convergence_panel_html = f"""
    <div class="convergence-panel">
      <div class="convergence-score">{convergence_display}</div>
      <div class="convergence-text">{syn.get("convergence_summary", "Signal synthesis unavailable.")}</div>
    </div>"""

    # Override warning block (only when bet_override is set)
    override_html = ""
    if bet_data.get("bet_override"):
        override_html = f'<div class="override-warning">&#9888;&nbsp; {bet_data["bet_override"]}</div>'

    # Disagreement note (only when Claude flags a conflict)
    disagreement_note = syn.get("disagreement_note")
    disagreement_html = ""
    if scores and disagreement_note and str(disagreement_note).lower() not in ("null", "none", ""):
        disagreement_html = f"""
  <div class="disagreement-note">
    <div class="skeptic-label">What would resolve this disagreement</div>
    <div style="font-size:13px;color:#44403C;line-height:1.6;">{disagreement_note}</div>
  </div>"""

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

  /* Convergence panel */
  .convergence-panel {{
    background: #F0EDE8; border: 1px solid #E0DDD7; border-radius: 8px;
    padding: 12px 14px; display: flex; align-items: flex-start; gap: 14px;
  }}
  .convergence-score {{ font-size: 28px; font-weight: 700; color: #1C1917; flex-shrink: 0; line-height: 1.1; }}
  .convergence-denom {{ font-size: 14px; font-weight: 400; color: #78716C; }}
  .convergence-text  {{ font-size: 14px; color: #1C1917; line-height: 1.6; flex: 1; }}
  .convergence-breakdown {{ margin-top: 6px; }}
  .breakdown-row {{
    display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
    margin-bottom: 5px;
  }}
  .breakdown-row:last-child {{ margin-bottom: 0; }}
  .breakdown-label {{
    font-size: 10px; font-weight: 700; color: #78716C;
    text-transform: uppercase; letter-spacing: 0.06em;
    margin-right: 4px; white-space: nowrap; flex-shrink: 0;
    min-width: 110px;
  }}

  /* Override warning */
  .override-warning {{
    background: #FEF3C7; border: 1px solid #F59E0B;
    border-radius: 6px; padding: 10px 14px;
    font-size: 12px; color: #78350F; font-weight: 500;
    margin: 12px 16px 0;
  }}

  /* India-fit stacked rows */
  .india-row-stack {{ padding: 10px 0; border-bottom: 1px solid #EDE9E4; }}
  .india-row-stack:last-child {{ border-bottom: none; }}
  .india-row-top {{
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;
  }}
  .india-key {{ font-size: 13px; font-weight: 500; color: #1C1917; }}
  .india-row-reason {{ font-size: 12px; color: #57534E; line-height: 1.55; }}
  .india-occasion-val {{ font-size: 13px; color: #44403C; }}
  .india-badge-yes     {{ background: #DCFCE7; color: #14532D; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}
  .india-badge-partial {{ background: #FEF3C7; color: #92400E; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}
  .india-badge-no      {{ background: #FEE2E2; color: #7F1D1D; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 3px; white-space: nowrap; }}

  /* Bet block */
  .bet-section {{ padding: 0; border-bottom: none; }}
  .bet-block {{ background: #1C1917; padding: 16px 18px; }}
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
    padding: 14px 18px 16px; font-size: 13px; color: #78350F; line-height: 1.65;
  }}
  .skeptic-label {{
    font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.06em; color: #92400E; margin-bottom: 5px;
  }}

  /* Disagreement note */
  .disagreement-note {{
    background: #F7F5F0; border-top: 1px solid #EDE9E4;
    padding: 12px 18px 18px;
    border-radius: 0 0 12px 12px;
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
        <div class="signal-name">Myntra / Meesho catalog + price health</div>
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

    <div class="signal-row">
      <div>
        <div class="signal-name">News coverage (Google News India)</div>
        <div class="signal-evidence">{_news["evidence"]}</div>
      </div>
      <span class="{_news["badge_class"]}">{_news["badge_text"]}</span>
    </div>

  </div>

  <!-- Section 2: Convergence -->
  <div class="result-section">
    <div class="section-eyebrow">Signal convergence</div>
    {convergence_panel_html}
  </div>

  {override_html}

  <!-- Section 3: India-fit check -->
  <div class="result-section" style="margin-top: {('12px' if bet_data.get('bet_override') else '0')};">
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
      <div class="bet-reason-text">{syn.get("bet_reasoning", "")}</div>
    </div>
  </div>

  <!-- Skepticism flag -->
  <div class="skeptic-flag">
    <div class="skeptic-label">&#9888; Skepticism flag</div>
    {syn.get("skepticism_flag", "Apply your own skepticism — Claude synthesis unavailable.")}
  </div>

  {disagreement_html}

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

  section[data-testid="stSidebar"] { background: #F7F5F0; }

  .signals-timestamp {
    font-size: 11px; color: #A8A29E;
    text-align: right; margin-top: 4px; margin-bottom: 8px;
  }

  .app-header {
    background: #1C1917; color: #F5F0EB;
    padding: 20px 28px; border-radius: 10px; margin-bottom: 24px;
  }
  .app-header h1 { font-size: 18px; font-weight: 600; color: #F5F0EB; margin: 0; }
  .app-header p  { font-size: 14px; color: #F5F0EB; margin: 4px 0 0; }

  .streamlit-expanderHeader {
    font-size: 12px !important; font-weight: 500 !important;
    color: #78716C !important; background: transparent !important;
    border: none !important; padding: 8px 0 !important;
  }
  .streamlit-expanderContent { border: none !important; padding: 8px 0 0 !important; }

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

  .input-label { font-size: 10.5px; font-weight: 600; color: #78716C; text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 6px; }

  .stTextInput input { border-radius: 8px; border: 1.5px solid #E8E3DA; background: #FAF9F7; font-size: 14px; padding: 10px 14px; }
  .stTextInput input:focus { border-color: #292524; box-shadow: 0 0 0 2px rgba(41,37,36,0.08); }

  .stButton button { background: #292524; color: #F5F0EB; border: none; border-radius: 8px; font-weight: 500; padding: 10px 20px; width: 100%; font-size: 14px; }

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

    st.markdown("""
<div class="app-header">
  <h1>📊 Trend Signal Advisor</h1>
  <p>India womenswear &nbsp;·&nbsp; Value fashion &nbsp;·&nbsp; Early signal intelligence</p>
</div>
""", unsafe_allow_html=True)

    with st.expander("What is this tool? ↓", expanded=False):
        st.markdown("""
<div class="hero-section">
  <div class="hero-headline">Is this trend worth a bet?</div>
  <div class="hero-body">
    For category buyers at value-fashion retailers. By the time a trend appears in your
    sales data, the buying window is already gone. This tool checks early evidence from
    4 independent sources — before demand is obvious.
  </div>
  <div class="hero-pills">
    <span class="hero-pill">Google Trends India</span>
    <span class="hero-pill">Myntra / Meesho catalog</span>
    <span class="hero-pill">Web social signal</span>
    <span class="hero-pill">Google News India</span>
  </div>
  <div class="hero-steps">
    <div class="hero-step"><div class="hero-step-num">01</div><div class="hero-step-text">Enter a trend keyword</div></div>
    <div class="hero-step"><div class="hero-step-num">02</div><div class="hero-step-text">4 sources vote independently</div></div>
    <div class="hero-step"><div class="hero-step-num">03</div><div class="hero-step-text">Get a defensible recommendation</div></div>
  </div>
  <div class="hero-disclaimer">
    This tool helps you reason through uncertainty — not decide for you.
    Always apply your store-floor knowledge alongside the signal.
  </div>
</div>
""", unsafe_allow_html=True)

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

            # Legacy bet sizing for demo JSONs (old 3-signal scoring)
            pos_d = count_india_fit_positives(india_fit_d)
            if conv_total_d >= 2.5 and pos_d >= 4:
                bet_d = {"bet": "Deeper buy — strong convergent signal", "bet_class": "deeper", "bet_override": None, "desc_prefix": ""}
            elif conv_total_d >= 1.5 and pos_d >= 3:
                bet_d = {"bet": "Trial buy — watch 4-week sell-through", "bet_class": "", "bet_override": None, "desc_prefix": ""}
            elif conv_total_d >= 1.0 and pos_d >= 2:
                bet_d = {"bet": "Small trial only — high uncertainty", "bet_class": "small-trial", "bet_override": None, "desc_prefix": ""}
            else:
                bet_d = {"bet": "Monitor only — do not buy yet", "bet_class": "monitor", "bet_override": None, "desc_prefix": ""}

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
            gt   = get_google_trends_signal(kw)
            mkt  = get_marketplace_signal(kw)
            soc  = get_social_signal(kw)
            news = get_news_signal(kw)

            scores = compute_convergence(gt, mkt, soc, news)
            syn    = synthesize_with_claude(kw, gt, mkt, soc, news, scores)

        india_fit           = syn.get("india_fit", {})
        india_fit_positives = count_india_fit_positives(india_fit)
        bet_data            = compute_bet(scores, mkt, india_fit, india_fit_positives)

        card = build_card_html(
            kw, gt, mkt, soc, syn, scores["display"],
            india_fit, bet_data, news, scores,
        )
        components.html(card, height=estimate_card_height(india_fit, syn, bet_data, scores), scrolling=False)

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
                "convergence_total": scores["weighted_score"],
                "bet": bet_data["bet"],
                "bet_class": bet_data["bet_class"],
            }
            with open(os.path.join(SAMPLE_DIR, fname), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

    # ── About these signals expander ───────────────────────────────────────────
    with st.expander("About these signals ↓", expanded=False):
        st.markdown("""
**Google Trends India** — weight 1.5x
Reflects relative search interest in India over the past 90 days, not absolute volume. A score of 100 means peak popularity in the period — not "100 searches." A flat or falling score does not mean the trend is dead; it may already be mainstream. *When a compound keyword scores near-zero, the tool automatically retries with a broader keyword.*

---

**Myntra / Meesho catalog + price health (via Serper)** — weight 1.0x
Two queries against India's largest fashion marketplaces. Query 1: catalog presence — how many products are listed and whether sellers describe them as new launches. Query 2: price pressure — are those products being discounted heavily, which signals oversupply or slow sell-through. Limitation: Serper returns Google-indexed snippets not live catalog data — discount detection depends on whether discount text appears in titles/snippets.

---

**Web social signal (search-indexed)** — weight 0.5x
Searches Google for pages discussing this trend alongside Instagram, reels, and influencer content. This is NOT direct Instagram data — Instagram blocks search engines. Lower weight because social buzz often leads demand by weeks but can also be empty hype that never converts.

---

**Google News India (via Serper)** — weight 0.75x
Searches Google News for recent articles mentioning this trend in Indian fashion and retail context. Uses the same Serper API as Sources 2 and 3 — no additional key required. Limitation: skews toward English-language media. PR and sponsored content can inflate this signal.

---

**Convergence score** is the weighted sum of all 4 signals, max 4.5. The buying recommendation also applies override rules that can block a buy even with a high score — if the marketplace shows oversupply combined with weak search demand, or if India-fit fails hard on price or climate.
""")
