"""
Live coverage test — 15 kurti styles across all recommendation tiers.
Calls real APIs (SerpApi, Serper, Anthropic). Results saved to test_coverage_results.json.
Run: python test_coverage_run.py
"""
import sys, types, io, json, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

# ── Streamlit stub (same as run_tests.py) ─────────────────────────────────────
st_stub = types.ModuleType("streamlit")

class _AttrDict(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v
    def __contains__(self, k): return dict.__contains__(self, k)

st_stub.session_state = _AttrDict()
st_stub.secrets = {}
st_stub.set_page_config = st_stub.markdown = st_stub.info = st_stub.warning = st_stub.stop = st_stub.error = lambda *a, **kw: None
class FakeCtx:
    def __enter__(self): return self
    def __exit__(self, *a): pass
st_stub.columns = lambda x: [FakeCtx() for _ in range(len(x) if hasattr(x, "__len__") else x)]
st_stub.expander = st_stub.spinner = lambda *a, **kw: FakeCtx()
st_stub.form = lambda *a, **kw: FakeCtx()
st_stub.text_input = lambda *a, **kw: ""
st_stub.button = st_stub.form_submit_button = lambda *a, **kw: False
st_stub.radio = lambda *a, **kw: ""
st_stub.sidebar = types.SimpleNamespace(
    markdown=lambda *a, **kw: None,
    selectbox=lambda *a, **kw: "— select —",
)
sys.modules["streamlit"] = st_stub
sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
sys.modules["streamlit.components.v1"] = types.SimpleNamespace(html=lambda *a, **kw: None)

from app import (
    get_google_trends_signal, get_marketplace_signal,
    get_social_signal, get_news_signal,
    compute_convergence, compute_bet, synthesize_with_claude,
    count_india_fit_positives, MAX_SCORE, _score_label, _buying_horizon_season,
)

# ── 15 keywords chosen to span all recommendation tiers ───────────────────────
# Mix: mainstream trending, niche craft, seasonal, oversupply-risk, fading
KEYWORDS = [
    # Expected STRONGER signals
    "chikankari cotton kurti",
    "mirror work kurti",
    "kaftan kurti",
    "anarkali kurti set",
    "linen co-ord kurti set",

    # Expected MODERATE signals
    "bandhani print kurti",
    "block print angrakha kurti",
    "phulkari embroidery kurti",
    "sequin kurti",
    "kantha stitch kurti",

    # Expected LOWER/NICHE signals
    "ikat print kurti",
    "organza kurti",
    "bagru block print kurti",
    "mukaish embroidery kurti",  # existing demo — good reference
    "tie dye kurti",
]

season = _buying_horizon_season()
print(f"\nBuying horizon season: {season}")
print(f"Testing {len(KEYWORDS)} kurti styles...\n")
print("=" * 70)

results = []

for i, kw in enumerate(KEYWORDS, 1):
    print(f"\n[{i:02d}/{len(KEYWORDS)}] ─── {kw.upper()} ───")

    try:
        # 1. Run all 4 signals
        print("  Fetching Google Trends...", end=" ", flush=True)
        gt = get_google_trends_signal(kw)
        print(f"{gt['badge_text']}  (keyword used: {gt.get('actual_keyword', kw)}{' [broadened]' if gt.get('broadened') else ''})")

        print("  Fetching Marketplace...", end=" ", flush=True)
        mkt = get_marketplace_signal(kw)
        print(f"{mkt['badge_text']}  (listings: {mkt.get('catalog_count',0)}, cat_pages: {mkt.get('category_pages',0)}, heavy_disc: {mkt.get('heavy_disc_count',0)}, disc_hits: {mkt.get('discount_hits',0)})")

        print("  Fetching Social...", end=" ", flush=True)
        soc = get_social_signal(kw)
        print(f"{soc['badge_text']}")

        print("  Fetching News...", end=" ", flush=True)
        news = get_news_signal(kw)
        print(f"{news['badge_text']}  (articles: {news.get('article_count',0)})")

        # 2. Convergence
        scores = compute_convergence(gt, mkt, soc, news)
        ws = scores["weighted_score"]
        print(f"\n  SCORE: {ws:.2f}/{MAX_SCORE}  [{_score_label(ws)}]")
        print(f"  Breakdown → Trends: {scores['trends_raw']:.2f}×1.5={scores['trends_raw']*1.5:.2f}  "
              f"Market: {scores['market_raw']:.2f}×1.0={scores['market_raw']:.2f}  "
              f"Social: {scores['social_raw']:.2f}×0.5={scores['social_raw']*0.5:.2f}  "
              f"News: {scores['news_raw']:.2f}×0.75={scores['news_raw']*0.75:.2f}")

        # 3. Claude synthesis (real call for india_fit + bet_reasoning)
        print("  Running Claude synthesis...", end=" ", flush=True)
        syn = synthesize_with_claude(kw, gt, mkt, soc, news, scores)
        india_fit = syn.get("india_fit", {})
        india_fit_positives = count_india_fit_positives(india_fit)
        print(f"India fit: {india_fit_positives}/4")

        # 4. Bet
        bet_data = compute_bet(scores, mkt, india_fit, india_fit_positives)
        bet = bet_data["bet"]
        override = bet_data.get("bet_override")

        print(f"\n  ★ RECOMMENDATION: {bet}")
        if override:
            print(f"  ⚠ OVERRIDE: {override}")
        print(f"  India fit → Price: {india_fit.get('price_band','?')}  "
              f"Climate({season}): {india_fit.get('climate_fit','?')}  "
              f"Cultural: {india_fit.get('cultural_fit','?')}  "
              f"VF-buyer: {india_fit.get('value_fashion_fit','?')}")
        print(f"  Reasoning: {syn.get('bet_reasoning','—')[:120]}...")
        print(f"  Skepticism: {syn.get('skepticism_flag','—')[:100]}...")
        print(f"  Logic rule: {bet_data.get('bet_logic_tooltip','—')}")

        results.append({
            "keyword": kw,
            "trends_badge": gt["badge_text"],
            "trends_direction": gt.get("direction",""),
            "trends_actual_kw": gt.get("actual_keyword", kw),
            "trends_broadened": gt.get("broadened", False),
            "market_badge": mkt["badge_text"],
            "market_listings": mkt.get("catalog_count", 0),
            "market_discounts": mkt.get("discount_hits", 0),
            "social_badge": soc["badge_text"],
            "news_badge": news["badge_text"],
            "news_articles": news.get("article_count", 0),
            "score": round(ws, 2),
            "score_label": _score_label(ws),
            "trends_raw": scores["trends_raw"],
            "market_raw": scores["market_raw"],
            "social_raw": scores["social_raw"],
            "news_raw": scores["news_raw"],
            "india_fit_positives": india_fit_positives,
            "price_band": india_fit.get("price_band",""),
            "climate_fit": india_fit.get("climate_fit",""),
            "cultural_fit": india_fit.get("cultural_fit",""),
            "vf_fit": india_fit.get("value_fashion_fit",""),
            "bet": bet,
            "bet_override": override,
            "bet_logic": bet_data.get("bet_logic_tooltip",""),
            "bet_reasoning": syn.get("bet_reasoning",""),
            "skepticism": syn.get("skepticism_flag",""),
            "disagreement": syn.get("disagreement_note",""),
        })

        # Brief pause between keywords to avoid rate limiting
        if i < len(KEYWORDS):
            time.sleep(2)

    except Exception as e:
        print(f"\n  ERROR: {e}")
        results.append({"keyword": kw, "error": str(e)})

# ── Summary table ─────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY TABLE")
print("=" * 70)
print(f"{'#':<3} {'Keyword':<32} {'Score':>6} {'Tier':<18} {'Recommendation':<35}")
print("-" * 70)

tier_counts = {}
for i, r in enumerate(results, 1):
    if "error" in r:
        print(f"{i:<3} {r['keyword']:<32} ERROR")
        continue
    bet = r["bet"]
    tier = r["score_label"]
    tier_counts[tier] = tier_counts.get(tier, 0) + 1
    print(f"{i:<3} {r['keyword']:<32} {r['score']:>5.2f}  {tier:<18} {bet[:34]}")

print("\nTier distribution:")
for tier, count in sorted(tier_counts.items()):
    print(f"  {tier}: {count}")

# ── Save results ──────────────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(__file__), "test_coverage_results.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump({"season": season, "results": results}, f, ensure_ascii=False, indent=2)
print(f"\nFull results saved to: {out_path}")
