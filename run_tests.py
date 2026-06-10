"""
Comprehensive test suite — unit + schema + edge cases.
Run: python run_tests.py
"""
import sys, types, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()

# ── Streamlit stub ────────────────────────────────────────────────────────────
st_stub = types.ModuleType("streamlit")

class _AttrDict(dict):
    """Dict that also supports attribute access (mirrors st.session_state)."""
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
st_stub.sidebar = types.SimpleNamespace(
    markdown=lambda *a, **kw: None,
    selectbox=lambda *a, **kw: "— select —",
)
sys.modules["streamlit"] = st_stub
sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
sys.modules["streamlit.components.v1"] = types.SimpleNamespace(html=lambda *a, **kw: None)

from app import (
    score_signal, compute_convergence, compute_bet,
    count_india_fit_positives, build_card_html, estimate_card_height,
    WEIGHT_TRENDS, WEIGHT_MARKET, WEIGHT_SOCIAL, WEIGHT_NEWS, MAX_SCORE,
    DEMO_FILE_MAP, SAMPLE_DIR,
)

failures = []
passed = 0

def check(label, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failures.append(label + (f" [{detail}]" if detail else ""))
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 1. score_signal ===")
cases = [
    # Positive tier (1.0)
    ("rising", 1.0), ("↑ Rising", 1.0), ("strong", 1.0), ("↑ Strong", 1.0),
    ("active", 1.0), ("active coverage", 1.0), ("↑ Active coverage", 1.0),
    ("healthy pricing", 1.0), ("active discussion", 1.0),
    ("↑ Strong — new listings, healthy pricing", 1.0),
    # Oversupply penalty (0.25)
    ("oversupply", 0.25), ("heavily discounted", 0.25),
    ("⚠ Listed but heavily discounted", 0.25),
    # Mid tier (0.5)
    ("flat", 0.5), ("→ Flat", 0.5), ("moderate", 0.5),
    ("→ Moderate catalog presence", 0.5), ("some", 0.5),
    ("→ Some coverage", 0.5), ("some coverage", 0.5),
    ("mentions", 0.5), ("coverage", 0.5),
    # Zero tier
    ("unknown", 0.0), ("none", 0.0), ("", 0.0), ("unavailable", 0.0),
    ("— Unavailable", 0.0), ("falling", 0.0), ("↓ Falling", 0.0),
    ("— No recent news", 0.0), ("— Not found in marketplace", 0.0),
    ("↓ Sparse catalog presence", 0.0),  # weak marketplace badge — "sparse" removed from mid-tier
    ("↓ Weak", 0.0),
    ("sparse", 0.0),  # removed from mid-tier to prevent "↓ Sparse catalog presence" scoring 0.5
]
for val, exp in cases:
    got = score_signal(val)
    check(f"score_signal({repr(val)[:35]}) == {exp}", got == exp, f"got {got}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. compute_convergence ===")

def mk_signals(d, mb, ss, nb, health="moderate", disc=2):
    gt   = {"direction": d, "badge_text": d, "badge_class": "x", "evidence": "", "actual_keyword": "k", "broadened": False, "fetched_at": "now"}
    mkt  = {"badge_text": mb, "badge_class": "x", "strength": "m", "evidence": "", "market_health": health, "catalog_count": 5, "discount_hits": disc}
    soc  = {"strength": ss, "badge_text": ss, "badge_class": "x", "evidence": ""}
    news = {"badge_text": nb, "badge_class": "x", "evidence": "", "article_count": 2, "top_headlines": []}
    return gt, mkt, soc, news

# Max score case
gt, mkt, soc, news = mk_signals("rising", "↑ Strong — new listings, healthy pricing", "strong", "↑ Active coverage")
sc = compute_convergence(gt, mkt, soc, news)
check("max weighted_score == 3.75", abs(sc["weighted_score"] - 3.75) < 0.001, sc["weighted_score"])
check("max demand_score == 2.5", abs(sc["demand_score"] - 2.5) < 0.001, sc["demand_score"])
check("max buzz_score == 1.25", abs(sc["buzz_score"] - 1.25) < 0.001, sc["buzz_score"])
check("display format correct", sc["display"] == f"3.8 / {MAX_SCORE}", sc["display"])

# Oversupply market_raw = 0.25
gt, mkt, soc, news = mk_signals("flat", "⚠ Listed but heavily discounted", "moderate", "→ Some coverage", "oversupply", 6)
sc2 = compute_convergence(gt, mkt, soc, news)
check("oversupply market_raw == 0.25", abs(sc2["market_raw"] - 0.25) < 0.001, sc2["market_raw"])
exp_ws = 0.5 * WEIGHT_TRENDS + 0.25 * WEIGHT_MARKET + 0.5 * WEIGHT_SOCIAL + 0.5 * WEIGHT_NEWS
check(f"oversupply weighted_score == {exp_ws:.2f}", abs(sc2["weighted_score"] - exp_ws) < 0.001, sc2["weighted_score"])

# news=None guard  (social_raw=1.0 because "strong" scores 1.0, then *0.5 = 0.5)
gt2, mkt2, soc2, _ = mk_signals("rising", "↑ Strong", "strong", "↑ Active coverage")
sc3 = compute_convergence(gt2, mkt2, soc2, None)
exp_no_news = 1.0 * WEIGHT_TRENDS + 1.0 * WEIGHT_MARKET + 1.0 * WEIGHT_SOCIAL + 0.0 * WEIGHT_NEWS
check("news=None gives news_raw == 0.0", sc3["news_raw"] == 0.0)
check(f"news=None weighted_score == {exp_no_news}", abs(sc3["weighted_score"] - exp_no_news) < 0.001, sc3["weighted_score"])

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. count_india_fit_positives ===")
GOOD = {"price_band": "Fits",         "climate_fit": "Yes", "cultural_fit": "Yes", "value_fashion_fit": "Yes"}
PART = {"price_band": "Partial",      "climate_fit": "Yes", "cultural_fit": "Yes", "value_fashion_fit": "Partial"}
BAD  = {"price_band": "Does not fit", "climate_fit": "No",  "cultural_fit": "Partial", "value_fashion_fit": "No"}
check("GOOD fit == 4", count_india_fit_positives(GOOD) == 4)
check("PART fit == 2", count_india_fit_positives(PART) == 2)
check("BAD fit == 0",  count_india_fit_positives(BAD) == 0)
check("empty fit == 0", count_india_fit_positives({}) == 0)
check("Fits in price_band counts", count_india_fit_positives({"price_band": "Fits", "climate_fit": "No", "cultural_fit": "No", "value_fashion_fit": "No"}) == 1)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 4. compute_bet — all tiers + all overrides ===")

def mk_scores(ws, demand, buzz, tr, mr, sr, nr):
    return {"weighted_score": ws, "demand_score": demand, "buzz_score": buzz,
            "trends_raw": tr, "market_raw": mr, "social_raw": sr, "news_raw": nr, "display": ""}

def mk_mkt(health, disc):
    return {"badge_text": "x", "badge_class": "x", "strength": "m", "evidence": "",
            "market_health": health, "catalog_count": 3, "discount_hits": disc}

# Normal tiers (no override expected)
tier_cases = [
    ("Deeper buy",    mk_scores(3.75, 2.5, 1.25, 1.0, 1.0, 1.0, 1.0), mk_mkt("moderate", 2), GOOD, 4),
    ("Trial buy",     mk_scores(2.6,  1.75, 0.85, 0.5, 1.0, 0.5, 0.5), mk_mkt("moderate", 2), GOOD, 3),
    ("Small trial",   mk_scores(1.75, 1.0,  0.75, 0.5, 0.5, 0.5, 0.5), mk_mkt("moderate", 2), PART, 2),
    ("Monitor only",  mk_scores(0.9,  0.5,  0.4,  0.0, 0.5, 0.5, 0.0), mk_mkt("moderate", 2), PART, 1),
    ("Do not buy — no meaningful", mk_scores(0.2, 0.0, 0.2, 0.0, 0.0, 0.5, 0.0), mk_mkt("moderate", 2), PART, 1),
]
for expected, sc_t, mkt_t, fit, pos in tier_cases:
    bet = compute_bet(sc_t, mkt_t, fit, pos)
    check(f"tier [{expected[:18]}] no override", expected.lower() in bet["bet"].lower() and not bet["bet_override"],
          f"bet={bet['bet']} ov={bool(bet['bet_override'])}")

# Override cases (override expected regardless of score)
# Hard India-fit failure: price_band = "Does not fit"
sc_strong = mk_scores(3.75, 2.5, 1.25, 1.0, 1.0, 1.0, 1.0)
bet = compute_bet(sc_strong, mk_mkt("moderate", 2), {"price_band": "Does not fit", "climate_fit": "Yes", "cultural_fit": "Yes", "value_fashion_fit": "Yes"}, 3)
check("price_band 'Does not fit' -> India-fit override", "india-fit" in bet["bet"].lower() and bet["bet_override"])

bet = compute_bet(sc_strong, mk_mkt("moderate", 2), {"price_band": "Fits", "climate_fit": "No", "cultural_fit": "Yes", "value_fashion_fit": "Yes"}, 3)
check("climate_fit 'No' -> India-fit override", "india-fit" in bet["bet"].lower() and bet["bet_override"])

bet = compute_bet(sc_strong, mk_mkt("moderate", 2), BAD, 0)
check("BAD fit -> India-fit override", "india-fit" in bet["bet"].lower() and bet["bet_override"])

# Oversupply override: market_health=oversupply AND trends_raw<=0.5
sc_flat = mk_scores(1.6, 0.75, 0.85, 0.5, 0.25, 0.5, 0.75)
bet = compute_bet(sc_flat, mk_mkt("oversupply", 6), PART, 2)
check("oversupply + flat trends -> oversupply override", "oversupply" in bet["bet"].lower() and bet["bet_override"])

# Oversupply does NOT fire when trends_raw > 0.5
sc_rising_os = mk_scores(3.0, 2.0, 1.0, 1.0, 0.25, 0.5, 0.75)
bet = compute_bet(sc_rising_os, mk_mkt("oversupply", 6), PART, 2)
check("oversupply + rising trends -> no override", not bet["bet_override"],
      f"bet={bet['bet']} ov={bet['bet_override']}")

# Buzz-without-demand override
sc_buzz = mk_scores(1.25, 0.0, 1.25, 0.0, 0.0, 1.0, 1.0)
bet = compute_bet(sc_buzz, mk_mkt("none", 0), GOOD, 4)
check("buzz without demand -> buzz override", "buzz" in bet["bet"].lower() and bet["bet_override"])

# buzz-without-demand does NOT fire when demand is present
sc_demand = mk_scores(3.75, 2.5, 1.25, 1.0, 1.0, 1.0, 1.0)
bet = compute_bet(sc_demand, mk_mkt("moderate", 2), GOOD, 4)
check("demand present -> no buzz override", not bet["bet_override"])

# India-fit override fires BEFORE oversupply (priority)
bet = compute_bet(sc_strong, mk_mkt("oversupply", 6), BAD, 0)
check("India-fit failure takes priority over oversupply", "india-fit" in bet["bet"].lower())

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 5. build_card_html — structure + edge cases ===")

def mk_card_inputs(override=None, disagreement=None):
    sc_c  = {"weighted_score": 2.5, "demand_score": 1.5, "buzz_score": 1.0,
              "trends_raw": 0.5, "market_raw": 1.0, "social_raw": 0.5, "news_raw": 0.75, "display": "2.5 / 4.5"}
    gt_c  = {"direction": "flat", "badge_class": "badge-flat", "badge_text": "→ Flat", "evidence": "test", "actual_keyword": "test", "broadened": False, "fetched_at": "now"}
    mkt_c = {"badge_text": "→ Moderate", "badge_class": "badge-flat", "strength": "moderate", "evidence": "test", "market_health": "moderate", "catalog_count": 5, "discount_hits": 2}
    soc_c = {"strength": "moderate", "badge_class": "badge-flat", "badge_text": "→ Moderate", "evidence": "test"}
    news_c= {"badge_text": "→ Some coverage", "badge_class": "badge-flat", "evidence": "2 articles", "article_count": 2, "top_headlines": []}
    syn_c = {"india_fit": GOOD, "convergence_summary": "ok", "signal_agreement": "Signals agree.",
             "disagreement_note": disagreement, "bet_reasoning": "Test reasoning.", "skepticism_flag": "Test flag.", "error": False}
    bet_c = {"bet": "Trial buy", "bet_class": "", "bet_override": override, "desc_prefix": ""}
    return gt_c, mkt_c, soc_c, news_c, syn_c, bet_c, sc_c

gt_c, mkt_c, soc_c, news_c, syn_c, bet_c, sc_c = mk_card_inputs()
html = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2.5 / 4.5", GOOD, bet_c, news_c, sc_c)
check("card HTML > 2000 chars", len(html) > 2000, len(html))
# score renders as  2.5<span> / 4.5</span>  — check both parts separately
check("weighted score 2.5 in card", ">2.5<" in html or "2.5<span" in html)
check("max score 4.5 in card", f"/ {MAX_SCORE}" in html)
check("bet in card", "Trial buy" in html)
check("signal agreement in card", "Signals agree." in html)
# CSS style block always contains class name; check for actual rendered div
check("no override div when None",  '<div class="override-warning">' not in html)
check("no disagreement div when None", '<div class="disagreement-note">' not in html)

# With override
gt_c, mkt_c, soc_c, news_c, syn_c, bet_c, sc_c = mk_card_inputs(override="Override: heavy discounting detected.")
html2 = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2.5 / 4.5", GOOD, bet_c, news_c, sc_c)
check("override div present", '<div class="override-warning">' in html2)
check("override text in card", "heavy discounting" in html2)

# With disagreement note
gt_c, mkt_c, soc_c, news_c, syn_c, bet_c, sc_c = mk_card_inputs(disagreement="Check Myntra sell-through.")
html3 = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2.5 / 4.5", GOOD, bet_c, news_c, sc_c)
check("disagreement-note div present", '<div class="disagreement-note">' in html3)
check("disagreement text in card", "Myntra sell-through" in html3)

# null disagreement variants — none should render the actual div
for null_val in [None, "null", "None", "none", ""]:
    gt_c, mkt_c, soc_c, news_c, syn_c, bet_c, sc_c = mk_card_inputs(disagreement=null_val)
    h = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2.5 / 4.5", GOOD, bet_c, news_c, sc_c)
    check(f"no disagree div for disagreement_note={repr(null_val)}", '<div class="disagreement-note">' not in h)

# news=None fallback
gt_c, mkt_c, soc_c, _, syn_c, bet_c, sc_c = mk_card_inputs()
html4 = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2.5 / 4.5", GOOD, bet_c, None, sc_c)
check("news=None renders fallback without crash", "Unavailable" in html4)

# Legacy path (no scores)
html5 = build_card_html("test kurti", gt_c, mkt_c, soc_c, syn_c, "2 / 3", GOOD, bet_c)
check("legacy path (no scores/news) renders without crash", len(html5) > 2000)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 6. estimate_card_height ===")
_, _, _, _, syn_c, bet_c, sc_c = mk_card_inputs()
_, _, _, _, _, bet_ov, _ = mk_card_inputs(override="Override text here")
_, _, _, _, syn_dis, _, _ = mk_card_inputs(disagreement="Disagreement note here")

h_base    = estimate_card_height(GOOD, syn_c, bet_c, sc_c)
h_override= estimate_card_height(GOOD, syn_c, bet_ov, sc_c)
h_disagree= estimate_card_height(GOOD, syn_dis, bet_c, sc_c)
h_both    = estimate_card_height(GOOD, syn_dis, bet_ov, sc_c)
h_legacy  = estimate_card_height(GOOD, syn_c, bet_c, None)

check("base height > 0", h_base > 0, h_base)
check("override adds height", h_override > h_base, f"override={h_override} base={h_base}")
check("disagree adds height", h_disagree > h_base, f"disagree={h_disagree} base={h_base}")
check("both adds most height", h_both >= h_override, f"both={h_both} override={h_override}")
check("legacy base < new base", h_legacy < h_base, f"legacy={h_legacy} new={h_base}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Demo JSON schema validation ===")
required_top  = ["keyword","analysed_at","trends_result","marketplace_result",
                 "social_result","news_result","weighted_score","demand_score",
                 "buzz_score","bet","bet_class","bet_override","claude_synthesis"]
required_syn  = ["india_fit","signal_agreement","disagreement_note","bet_reasoning","skepticism_flag"]
required_fit  = ["price_band","price_band_reason","climate_fit","climate_fit_reason",
                 "cultural_fit","cultural_fit_reason","value_fashion_fit","value_fashion_fit_reason","occasion_fit"]
required_mkt  = ["market_health","discount_hits","catalog_count"]
required_news = ["badge_text","article_count","top_headlines"]

json_files = [f for f in os.listdir(SAMPLE_DIR) if f.endswith(".json")]
check(f"5 demo JSONs present", len(json_files) == 5, json_files)

for fname in sorted(json_files):
    path = os.path.join(SAMPLE_DIR, fname)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    check(f"{fname} top-level keys", all(k in d for k in required_top),
          str([k for k in required_top if k not in d]))
    syn = d.get("claude_synthesis", {})
    check(f"{fname} claude_synthesis keys", all(k in syn for k in required_syn),
          str([k for k in required_syn if k not in syn]))
    fit = syn.get("india_fit", {})
    check(f"{fname} india_fit keys", all(k in fit for k in required_fit),
          str([k for k in required_fit if k not in fit]))
    mkt = d.get("marketplace_result", {})
    check(f"{fname} marketplace_result keys", all(k in mkt for k in required_mkt),
          str([k for k in required_mkt if k not in mkt]))
    news = d.get("news_result", {})
    check(f"{fname} news_result keys", all(k in news for k in required_news),
          str([k for k in required_news if k not in news]))
    check(f"{fname} weighted_score is float", isinstance(d.get("weighted_score"), (int, float)))
    check(f"{fname} bet is non-empty string", isinstance(d.get("bet"), str) and len(d["bet"]) > 5)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 8. DEMO_FILE_MAP consistency ===")
check("5 entries in DEMO_FILE_MAP", len(DEMO_FILE_MAP) == 5, len(DEMO_FILE_MAP))
for kw, fname in DEMO_FILE_MAP.items():
    fpath = os.path.join(SAMPLE_DIR, fname)
    check(f"DEMO_FILE_MAP[{repr(kw)}] file exists", os.path.exists(fpath), fpath)

# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  PASSED: {passed}   FAILED: {len(failures)}")
if failures:
    print("\nFailed tests:")
    for f in failures:
        print(f"  - {f}")
print("="*55)
sys.exit(0 if not failures else 1)
