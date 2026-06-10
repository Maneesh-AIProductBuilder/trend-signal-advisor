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
    "sharara kurti set":        "sharara_kurti_set.json",
    "schiffli cotton kurti":    "schiffli_cotton_kurti.json",
    "angrakha kurti":           "angrakha_kurti.json",
    "mukaish embroidery kurti": "mukaish_embroidery_kurti.json",
    "velvet palazzo suit":      "velvet_palazzo_suit.json",
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

        # tbs=qdr:m2 restricts results to the past 2 months — prevents old indexed
        # articles (2023, 2025 Diwali, etc.) from inflating the news score
        response = requests.post(
            "https://google.serper.dev/news",
            json={"q": f"{keyword} fashion india", "gl": "in", "num": 10, "tbs": "qdr:m2"},
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

        # Lower threshold vs. unfiltered: 2-month window returns fewer articles by design
        if article_count >= 2 and positive_hits >= 1:
            badge_class, badge_text = "badge-up",   "↑ Active coverage"
        elif article_count >= 1:
            badge_class, badge_text = "badge-flat", "→ Some coverage"
        else:
            badge_class, badge_text = "badge-na",   "— No recent news"

        result = {
            "status": "success",
            "badge_class": badge_class,
            "badge_text": badge_text,
            "evidence": (f"{article_count} articles in past 2 months · "
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
        "flat", "moderate", "some", "→", "mentions", "coverage",
    ]):
        return 0.5
    return 0.0


# ── Keyword scope validation ───────────────────────────────────────────────────
_BLOCKED_CATEGORIES = {
    "shoes", "shoe", "boot", "boots", "heel", "heels", "sandal", "sandals",
    "sneaker", "sneakers", "footwear", "slipper", "slippers", "loafer", "loafers",
    "bag", "bags", "handbag", "purse", "wallet", "clutch", "tote", "backpack",
    "electronics", "phone", "mobile", "laptop", "tablet", "charger", "earphones",
    "watch", "watches", "jewelry", "jewellery", "necklace", "bracelet", "ring",
    "furniture", "sofa", "table", "chair", "mattress",
    "toys", "toy",
    "makeup", "cosmetics", "skincare", "lipstick", "foundation", "perfume",
    "menswear", "boys", "kidswear", "kids", "children", "baby",
    "pet", "dog", "cat",
}

_APPAREL_SIGNALS = {
    "kurti", "kurta", "dress", "top", "blouse", "saree", "sari", "lehenga",
    "suit", "palazzo", "coord", "anarkali", "dupatta", "churidar", "salwar",
    "ethnic", "western", "embroidery", "print", "cotton", "silk", "fabric",
    "womenswear", "women", "ladies", "girl", "female", "fashion", "apparel",
    "clothing", "wear", "outfit", "set", "collection", "ghagra", "choli",
    "sharara", "skirt", "tunic", "kaftan", "jumpsuit", "maxi", "midi", "floral",
    "block", "mirror", "gota", "mukaish", "schiffli", "velvet", "angrakha",
    "indo", "kameez", "jacket", "cape", "overlay", "kurta",
}


def validate_keyword(kw):
    """Returns (status, message): True=valid, False=hard block, None=soft warn."""
    if len(kw.strip()) < 3:
        return False, "Please enter a more specific keyword (at least 3 characters)."
    words = set(kw.lower().replace("-", " ").split())
    blocked_hits = words & _BLOCKED_CATEGORIES
    if blocked_hits:
        term = next(iter(blocked_hits))
        return False, (
            f"This tool is designed for **India womenswear apparel trends** "
            f"(kurtis, dresses, ethnic wear, western tops, co-ords, etc.).\n\n"
            f"**'{kw}'** appears to be outside that scope (detected: *{term}*). "
            f"Please try a womenswear clothing keyword."
        )
    kw_lower = kw.lower()
    has_apparel = any(s in kw_lower for s in _APPAREL_SIGNALS)
    if not has_apparel:
        return None, (
            f"**Heads up:** '{kw}' doesn't contain obvious womenswear terms. "
            f"This tool works best with India womenswear keywords "
            f"(e.g. 'block print kurti', 'floral co-ord set'). "
            f"Results may have lower accuracy — apply extra skepticism."
        )
    return True, None


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


# ── Score qualitative label ────────────────────────────────────────────────────
def _score_label(ws):
    if ws >= 3.5:
        return "Strong signal"
    elif ws >= 2.5:
        return "Moderate signal"
    elif ws >= 1.5:
        return "Low confidence"
    else:
        return "Weak signal"


# ── What would change this recommendation ─────────────────────────────────────
def _what_changes_text(bet, scores, india_fit):
    ws  = scores.get("weighted_score", 0) if scores else 0
    ifp = count_india_fit_positives(india_fit) if india_fit else 0
    b   = bet.lower()

    if "deeper buy" in b:
        return (
            "All demand and India-fit conditions are currently met. "
            "Monitor Myntra sell-through at 6 weeks — if velocity stays above 50%, this confirms the signal."
        )
    elif "trial buy" in b:
        gap = round(3.5 - ws, 1)
        return (
            f"Score is {ws:.1f} / {MAX_SCORE}. A score of 3.5+ with all 4 India-fit checks passing "
            f"would move this to a Deeper buy (gap: {gap} pts). "
            f"A rising Google Trends signal or strong new marketplace listings without discounting would close it."
        )
    elif "small trial" in b:
        gap    = round(2.5 - ws, 1)
        if_gap = max(0, 3 - ifp)
        msg = f"Score is {ws:.1f} — needs 2.5+ for Trial buy (gap: {gap} pts). "
        if if_gap > 0:
            msg += f"Also needs {if_gap} more India-fit positive(s) (currently {ifp}/4). "
        msg += "Strong marketplace presence with new launches and healthy pricing would move this up."
        return msg
    elif "oversupply" in b:
        return (
            "Override lifts when: marketplace discount signals drop below threshold AND "
            "Google Trends shows a rising direction. Check again in 3–4 weeks."
        )
    elif "india-fit" in b:
        return (
            "Hard stop due to price band or climate mismatch. "
            "Override lifts only if the trend evolves to fit &#8377;399&#8211;&#8377;1,499 pricing — unlikely for most styles."
        )
    elif "buzz without demand" in b:
        return (
            "Override lifts when Google Trends or marketplace shows rising demand, not just editorial buzz. "
            "Watch for Myntra new listings at healthy prices over the next 4 weeks."
        )
    elif "monitor" in b:
        return (
            f"Score is {ws:.1f} — below the 1.5 threshold for any trial buy. "
            "If Google Trends rises sustainably over 4 weeks, or Myntra lists fresh inventory without discounting, recheck then."
        )
    else:
        return "No meaningful signal at this time. Recheck if search trends rise or marketplace activity picks up."


# ── What to track next ─────────────────────────────────────────────────────────
def _track_next(bet):
    b = bet.lower()
    if "deeper buy" in b:
        return "Track: Myntra sell-through at 6 weeks &middot; Target &gt;50%"
    elif "trial buy" in b:
        return "Track: Myntra sell-through at 4 weeks &middot; Target &gt;35%"
    elif "small trial" in b:
        return "Track: Meesho reorder rate at 3 weeks &middot; If &lt;20%, do not reorder"
    elif "monitor" in b:
        return "Recheck signals in 3 weeks &middot; Look for rising Trends + fresh marketplace listings"
    else:
        return "Recheck if marketplace health improves or search demand rises"


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

    # Score display with qualitative label
    if scores:
        ws = scores["weighted_score"]
        score_display_html = (
            f'<span style="font-size:26px;font-weight:700;color:#1C1917;line-height:1.1;">{ws:.1f}</span>'
            f'<span style="font-size:13px;color:#78716C;margin-left:4px;">/ {MAX_SCORE}</span>'
            f'<span style="font-size:10px;font-weight:600;color:#78716C;'
            f'background:#E8E3DA;padding:2px 8px;border-radius:10px;margin-left:8px;'
            f'vertical-align:middle;white-space:nowrap;">{_score_label(ws)}</span>'
        )
    else:
        score_display_html = f'<span style="font-size:22px;font-weight:700;color:#1C1917;">{convergence_display}</span>'

    # Convergence panel
    if scores:
        signal_agreement = syn.get("signal_agreement", syn.get("convergence_summary", ""))
        convergence_panel_html = f"""
    <div class="convergence-panel">
      <div style="margin-bottom:8px;">{score_display_html}</div>
      <div style="font-size:13px;color:#1C1917;line-height:1.5;margin-bottom:10px;">{signal_agreement}</div>
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
    </div>"""
    else:
        convergence_panel_html = f"""
    <div class="convergence-panel">
      <div style="margin-bottom:6px;">{score_display_html}</div>
      <div style="font-size:13px;color:#1C1917;">{syn.get("convergence_summary", "Signal synthesis unavailable.")}</div>
    </div>"""

    # Override warning — with trigger field hint
    override_html = ""
    if bet_data.get("bet_override"):
        price_val   = india_fit.get("price_band", "")
        climate_val = india_fit.get("climate_fit", "").strip()
        if "Does not fit" in price_val:
            trigger_hint = ' <span style="font-size:11px;opacity:0.75;">(see Price band below &#8595;)</span>'
        elif climate_val == "No":
            trigger_hint = ' <span style="font-size:11px;opacity:0.75;">(see Climate fit below &#8595;)</span>'
        else:
            trigger_hint = ""
        override_html = (
            f'<div class="override-warning">&#9888;&nbsp; '
            f'{bet_data["bet_override"]}{trigger_hint}</div>'
        )

    # Disagreement note
    disagreement_note = syn.get("disagreement_note")
    disagreement_html = ""
    if scores and disagreement_note and str(disagreement_note).lower() not in ("null", "none", ""):
        disagreement_html = f"""
  <div class="disagreement-note">
    <div class="skeptic-label">What would resolve this disagreement</div>
    <div style="font-size:13px;color:#44403C;line-height:1.6;">{disagreement_note}</div>
  </div>"""

    # "What would change this?" collapsible
    what_changes_html = f"""
  <details class="what-changes">
    <summary class="what-changes-summary">&#9656;&nbsp; What would change this recommendation?</summary>
    <div class="what-changes-body">{_what_changes_text(bet_data["bet"], scores, india_fit)}</div>
  </details>"""

    # Track next line inside bet block
    track_html = f'<div class="track-next">{_track_next(bet_data["bet"])}</div>'

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
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 10px 0; border-bottom: 1px solid #F5F5F4;
  }}
  .signal-row:last-child {{ border-bottom: none; }}
  .signal-name {{
    font-size: 13px; font-weight: 600; color: #1C1917; margin-bottom: 3px;
    display: flex; align-items: center; gap: 5px;
  }}
  .signal-evidence {{ font-size: 12px; color: #57534E; line-height: 1.45; }}

  /* Signal ⓘ tooltip */
  .tooltip-wrap {{ position: relative; display: inline-block; flex-shrink: 0; }}
  .tooltip-i {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 14px; height: 14px; background: #D6D3D1; color: #57534E;
    border-radius: 50%; font-size: 9px; font-weight: 700;
    cursor: help; font-style: normal; user-select: none;
  }}
  .tooltip-box {{
    display: none; position: absolute; z-index: 999;
    left: 50%; transform: translateX(-50%); top: 20px;
    background: #1C1917; color: #E7E5E4;
    font-size: 11px; font-weight: 400; line-height: 1.55;
    padding: 8px 10px; border-radius: 6px;
    width: 230px; pointer-events: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  }}
  .tooltip-box b {{ color: #FFFFFF; font-weight: 600; }}
  .tooltip-wrap:hover .tooltip-box {{ display: block; }}

  /* Badges */
  .badge-up   {{ background: #DCFCE7; color: #14532D; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; margin-top: 2px; }}
  .badge-flat {{ background: #FEF9C3; color: #713F12; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; margin-top: 2px; }}
  .badge-down {{ background: #FEE2E2; color: #7F1D1D; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; margin-top: 2px; }}
  .badge-na   {{ background: #F3F4F6; color: #6B7280; font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; margin-left: 12px; margin-top: 2px; }}

  /* Convergence panel */
  .convergence-panel {{
    background: #F0EDE8; border: 1px solid #E0DDD7; border-radius: 8px;
    padding: 12px 14px;
  }}
  .convergence-breakdown {{ margin-top: 4px; }}
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

  /* Bet block — FIRST */
  .bet-section {{ padding: 0; }}
  .bet-block {{ background: #1C1917; padding: 16px 18px; }}
  .bet-block.deeper      {{ background: #14532D; }}
  .bet-block.small-trial {{ background: #92400E; }}
  .bet-block.monitor     {{ background: #44403C; }}
  .bet-eyebrow {{
    font-size: 9.5px; font-weight: 700; color: #A8A29E;
    text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px;
  }}
  .bet-size-text {{ font-size: 16px; font-weight: 600; color: #F5F0EB; margin-bottom: 6px; }}
  .bet-reason-text {{ font-size: 13px; color: #D6D3D1; line-height: 1.65; margin-bottom: 10px; }}
  .track-next {{
    font-size: 11px; color: #A8A29E;
    border-top: 1px solid rgba(255,255,255,0.1);
    padding-top: 8px; line-height: 1.5;
  }}

  /* What would change this */
  .what-changes {{ border-bottom: 1px solid #EDE9E4; }}
  .what-changes-summary {{
    font-size: 12px; font-weight: 500; color: #78716C;
    padding: 10px 16px; cursor: pointer; list-style: none;
    display: flex; align-items: center; gap: 4px;
    user-select: none;
  }}
  .what-changes-summary::-webkit-details-marker {{ display: none; }}
  .what-changes-summary:hover {{ color: #44403C; background: #F7F5F2; }}
  details[open] .what-changes-summary {{ color: #44403C; }}
  .what-changes-body {{
    font-size: 13px; color: #57534E; line-height: 1.65;
    padding: 0 16px 14px; border-top: 1px solid #F0EDE8;
    background: #FDFCFB;
  }}

  /* Skepticism flag — elevated */
  .skeptic-section {{ padding: 14px 16px 0; border-bottom: 1px solid #EDE9E4; }}
  .skeptic-flag {{
    background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 6px;
    padding: 12px 14px; font-size: 13px; color: #78350F; line-height: 1.65;
    margin-bottom: 14px;
  }}
  .skeptic-header {{
    font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.06em; color: #92400E; margin-bottom: 5px;
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

  <!-- 1: Buying recommendation FIRST -->
  <div class="bet-section">
    <div class="bet-block{bet_class_attr}">
      <div class="bet-eyebrow">Buying recommendation</div>
      <div class="bet-size-text">{bet_data["bet"]}</div>
      <div class="bet-reason-text">{syn.get("bet_reasoning", "")}</div>
      {track_html}
    </div>
  </div>

  <!-- 2: What would change this -->
  {what_changes_html}

  <!-- Override warning (if present) -->
  {override_html}

  <!-- 3: Signal sources (with ⓘ tooltips) -->
  <div class="result-section" style="margin-top:{('12px' if bet_data.get('bet_override') else '0')};">
    <div class="section-eyebrow">Signal sources</div>

    <div class="signal-row">
      <div style="flex:1;min-width:0;">
        <div class="signal-name">
          Google Trends India
          <span class="tooltip-wrap">
            <i class="tooltip-i">i</i>
            <span class="tooltip-box">
              <b>Proves:</b> Direction of search curiosity in India (90 days)<br><br>
              <b>Cannot prove:</b> Purchase intent — a viral reel can spike this without generating any sales
            </span>
          </span>
        </div>
        <div class="signal-evidence">{gt["evidence"]}</div>
      </div>
      <span class="{gt["badge_class"]}">{gt["badge_text"]}</span>
    </div>

    <div class="signal-row">
      <div style="flex:1;min-width:0;">
        <div class="signal-name">
          Myntra / Meesho catalog + price health
          <span class="tooltip-wrap">
            <i class="tooltip-i">i</i>
            <span class="tooltip-box">
              <b>Proves:</b> Catalog activity and pricing health on India's top fashion marketplaces<br><br>
              <b>Cannot prove:</b> Actual sell-through — sponsored listings can distort catalog count; discount detection depends on snippet text
            </span>
          </span>
        </div>
        <div class="signal-evidence">{mkt["evidence"]}</div>
      </div>
      <span class="{mkt["badge_class"]}">{mkt["badge_text"]}</span>
    </div>

    <div class="signal-row">
      <div style="flex:1;min-width:0;">
        <div class="signal-name">
          Web social signal (search-indexed)
          <span class="tooltip-wrap">
            <i class="tooltip-i">i</i>
            <span class="tooltip-box">
              <b>Proves:</b> Web-indexed pages mention this trend alongside creators and reels<br><br>
              <b>Cannot prove:</b> Real Instagram reach — Instagram blocks search engines; this is Google's index of social pages, not direct data
            </span>
          </span>
        </div>
        <div class="signal-evidence">{soc["evidence"]}</div>
      </div>
      <span class="{soc["badge_class"]}">{soc["badge_text"]}</span>
    </div>

    <div class="signal-row">
      <div style="flex:1;min-width:0;">
        <div class="signal-name">
          News coverage (Google News India)
          <span class="tooltip-wrap">
            <i class="tooltip-i">i</i>
            <span class="tooltip-box">
              <b>Proves:</b> Recent editorial coverage in Indian fashion media (past 2 months)<br><br>
              <b>Cannot prove:</b> Commercial demand — PR and sponsored content can inflate this signal
            </span>
          </span>
        </div>
        <div class="signal-evidence">{_news["evidence"]}</div>
      </div>
      <span class="{_news["badge_class"]}">{_news["badge_text"]}</span>
    </div>

  </div>

  <!-- 4: Overall signal strength -->
  <div class="result-section">
    <div class="section-eyebrow">Overall signal strength</div>
    {convergence_panel_html}
  </div>

  <!-- 5: India market fit -->
  <div class="result-section">
    <div class="section-eyebrow">India market fit</div>

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

  <!-- 6: Skepticism flag — elevated, bordered -->
  <div class="skeptic-section">
    <div class="skeptic-flag">
      <div class="skeptic-header">&#9888; Before you decide</div>
      {syn.get("skepticism_flag", "Apply your own skepticism — Claude synthesis unavailable.")}
    </div>
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
  .demo-suggestion { font-size: 11.5px; color: #9B9590; margin-top: 6px; line-height: 1.5; }

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


# ── Session state init ─────────────────────────────────────────────────────────
if "active_mode"      not in st.session_state: st.session_state.active_mode      = "none"
if "live_result"      not in st.session_state: st.session_state.live_result      = None
if "prev_demo_choice" not in st.session_state: st.session_state.prev_demo_choice = "— select —"

# ── Sidebar demo loader ────────────────────────────────────────────────────────
st.sidebar.markdown("### Try a demo")
st.sidebar.markdown(
    '<span style="font-size:12px;color:#9B9590;">See how the tool analyses a known trend — no API calls needed.</span>',
    unsafe_allow_html=True,
)
demo_choice = st.sidebar.selectbox(
    "Load a sample analysis:",
    ["— select —", "sharara kurti set", "schiffli cotton kurti",
     "angrakha kurti", "mukaish embroidery kurti", "velvet palazzo suit"],
    label_visibility="collapsed",
)

# When user explicitly changes demo selection, that clears any live result
if demo_choice != st.session_state.prev_demo_choice:
    if demo_choice != "— select —":
        st.session_state.active_mode = "demo"
        st.session_state.live_result = None
    st.session_state.prev_demo_choice = demo_choice


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

    # st.form submits on Enter key press — no extra button click needed
    with st.form("search_form", clear_on_submit=False):
        keyword = st.text_input(
            "",
            placeholder='e.g. "mirror embroidery kurti", "floral co-ord set"',
            label_visibility="collapsed",
        )
        analyse = st.form_submit_button("Analyse trend →", use_container_width=True)

    st.markdown(
        '<div class="demo-suggestion">Not sure what to try? '
        'Load an example from the sidebar, or try: <em>sharara kurti set</em> &nbsp;·&nbsp; <em>angrakha kurti</em></div>',
        unsafe_allow_html=True,
    )

    # ── Live analysis ──────────────────────────────────────────────────────────
    if analyse:
        kw = keyword.strip()
        if not kw:
            st.warning("Please enter a trend keyword before analysing.")
        else:
            valid, msg = validate_keyword(kw)
            if valid is False:
                st.error(msg)
            else:
                if valid is None:
                    st.warning(msg)

                # Live analysis always clears demo state
                st.session_state.active_mode = "live"

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
                st.session_state.live_result = {
                    "card":   card,
                    "height": estimate_card_height(india_fit, syn, bet_data, scores),
                    "ts":     gt.get("fetched_at", "N/A"),
                }

                # Auto-save if keyword matches a demo slot
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

    # ── Render result ──────────────────────────────────────────────────────────
    if st.session_state.active_mode == "live" and st.session_state.live_result:
        r = st.session_state.live_result
        components.html(r["card"], height=r["height"], scrolling=False)
        st.markdown(
            f'<div class="signals-timestamp">Signals fetched: {r["ts"]}</div>',
            unsafe_allow_html=True,
        )

    elif st.session_state.active_mode == "demo" and demo_choice != "— select —":
        fname = DEMO_FILE_MAP.get(demo_choice)
        fpath = os.path.join(SAMPLE_DIR, fname) if fname else None
        if fpath and os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                demo = json.load(f)

            st.info(f"📁 Demo mode — cached · {demo.get('analysed_at', 'unknown')}")

            gt_d        = demo["trends_result"]
            mkt_d       = demo["marketplace_result"]
            soc_d       = demo["social_result"]
            news_d      = demo.get("news_result", {})
            syn_d       = demo["claude_synthesis"]
            india_fit_d = syn_d.get("india_fit", {})

            scores_d = {
                "weighted_score": demo.get("weighted_score", 0),
                "demand_score":   demo.get("demand_score", 0),
                "buzz_score":     demo.get("buzz_score", 0),
                "display":        f"{demo.get('weighted_score', 0):.1f} / {MAX_SCORE}",
            }
            bet_d = {
                "bet":          demo.get("bet", "Monitor only — do not buy yet"),
                "bet_class":    demo.get("bet_class", "monitor"),
                "bet_override": demo.get("bet_override"),
                "desc_prefix":  "",
            }

            demo_card = build_card_html(
                demo["keyword"], gt_d, mkt_d, soc_d, syn_d,
                scores_d["display"], india_fit_d, bet_d, news_d, scores_d,
            )
            components.html(
                demo_card,
                height=estimate_card_height(india_fit_d, syn_d, bet_d, scores_d),
                scrolling=False,
            )
            st.markdown(
                f'<div class="signals-timestamp">Signals fetched: {gt_d.get("fetched_at", "N/A")}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.warning(f"Demo file not found for '{demo_choice}'.")
