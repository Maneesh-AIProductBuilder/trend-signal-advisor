# Trend Signal Advisor

**Live demo:** https://maneesh-trendsignal-advisor.streamlit.app/  
---

## 1. What I built and how to run it

A value-fashion category buyer commits inventory money to kurti styles 5–8 weeks before demand is visible in sales data. By then, the best supplier slots are gone. Early evidence exists — search intent, marketplace pricing, creator content, editorial coverage — but it is scattered, unreliable, and contradictory. No single signal is enough, and a confident-looking summary would be worse than useless.

**Trend Signal Advisor** researches four independent signal sources, scores their convergence, runs a deterministic India-fit check, and produces a buying recommendation with every reason for doubt visible. The output explicitly answers the four questions from the brief: *what looks real, what could mislead, what should the buyer do, and what improves next time.*

### Run locally

```bash
git clone https://github.com/Maneesh-AIProductBuilder/trend-signal-advisor
cd trend-signal-advisor
pip install -r requirements.txt

cp .env.example .env
# Fill in .env:
# SERPAPI_KEY=your_serpapi_key
# SERPER_API_KEY=your_serper_key
# ANTHROPIC_API_KEY=your_anthropic_key

streamlit run app.py
```

Opens at `http://localhost:8501`. Analysis takes 10–15 seconds — four live API calls run in sequence.

**Demo mode:** Select any of five cached analyses from the sidebar. No API calls are made. Five keywords were chosen to cover every recommendation tier so the full reasoning path is inspectable without live signals:

| Keyword | Recommendation | What it demonstrates |
|---|---|---|
| mirror work kurti | Trial buy | Healthy convergence, 3 India-fit criteria pass |
| anarkali kurti | Small trial | Rising trends, but buzz-only — demand moderate |
| mukaish embroidery kurti | Monitor only | Niche craft, sparse catalog, insufficient signal |
| sequin kurti | Do not buy — oversupply | Marketplace override: 60%+ discount snippets detected |
| chikankari kurti | Monitor — buzz without demand | Override: social/news active, but purchase intent weak |

*Note: "Deeper buy" is intentionally unreachable in June — it requires score ≥ 3.5 and all four India-fit criteria to pass. In the monsoon buying window, most embroidery-heavy kurtis fail climate fit for the upcoming season. This is correct tool behaviour, not a gap.*

**Input validation:** The tool blocks category names ("women kurtis", "buy kurtis online") and bare style words ("anarkali" without a garment term). It only accepts specific style + garment combinations, which is the only input type the signal pipeline can reason about meaningfully.

---

## 2. Source strategy

Four sources across three genuinely distinct data classes. Each source votes independently before Claude sees any of them — this prevents circular reasoning and makes the convergence score meaningful.

### Source 1 — Google Trends India (SerpApi)
**Data class:** Consumer demand signal | **Weight: 1.5×**

Measures real consumer search intent in India over 90 days, geo-filtered to `IN`. Unmanipulated — no supplier, creator, or advertiser can game it. A steady multi-week climb in the second half of the 90-day window is treated as a rising signal; a decline as falling; otherwise flat.

**Keyword broadening:** Compound kurti style terms ("mirror work kurti") often score near-zero on Google Trends — not because consumers lack interest, but because they search for "mirror kurti" or "mirror embroidery kurti" instead. When the exact phrase returns fewer than four weeks of data or all values ≤ 10, the tool automatically retries with a shorter version (drops the last word) and discloses which keyword was actually queried. This is a practical necessity and the disclosure keeps it honest.

**Where it misleads:** A flat reading does not mean a style is dead — it may have already peaked and moved into mainstream sales data. Vernacular and regional-language search terms are not captured by this API. Near-zero scores on compound niche phrases are data sparsity, not absence of demand.

**Why 90 days:** Long enough to distinguish a sustained climb from a one-week spike; short enough to remain a leading indicator rather than confirming what is already in sales reports.

---

### Source 2 — Myntra / Meesho catalog + price health (Serper)
**Data class:** Supply-side signal | **Weight: 1.0×**

Two parallel Serper queries:
- **Query 1 — Catalog presence:** `{keyword} site:myntra.com OR site:meesho.com` — counts results, parses URLs and snippets
- **Query 2 — Price pressure:** `{keyword} ("% off" OR "sale" OR "clearance") site:meesho.com OR site:myntra.com`

**Four-state interpretation logic:**

| State | Condition | Signal |
|---|---|---|
| ↑ Rising | ≥2 category-page URLs, zero 60%+ discount snippets | Healthy new supply entering; trend has earned a shelf |
| ⚠ Heavily discounted | ≥1 category page AND ≥2 snippets with 60%+ off | Oversupply — suppliers liquidating unsold stock |
| ↓ Sparse | Catalog present but no category pages | Niche or very early stage; not yet mainstream supply |
| → Moderate | Catalog present, mixed signals | Established but unremarkable supply position |

The key insight is **category-page URL detection**. Myntra gives a trend its own listing shelf only when it has meaningful sales volume (e.g., `myntra.com/anarkali-kurtas` — a single path segment). Meesho uses a `/pl/` path for category pages. A product-level URL (`myntra.com/kurtas/brand/product-name/buy/12345`) just means one SKU exists. This distinction — earned shelf vs. isolated listing — was the signal that previous marketplace heuristics (launch keyword counting) could not capture and was returning "Moderate" for every query. Category URL detection fixed that.

The oversupply detection (`60%+ discount in snippets`) directly implements the assignment brief's warning: *"marketplace ranks may be distorted by discounting or stockouts."* Rather than listing it as a limitation, the tool measures it and fires an override.

**Where it misleads:** Serper returns Google-indexed snippets, not live catalog data — there is up to 72 hours of staleness. Sponsored product listings appear in organic results and can inflate catalog counts. Discount text detection depends on whether sellers include percentages in page titles, which is inconsistent.

---

### Source 3 — Web social signal (Serper)
**Data class:** Buzz signal | **Weight: 0.5× (lowest)**

Query: `{keyword} Indian fashion Instagram reels` with `gl=in`. Counts how many web pages — articles, blogs, style guides, aggregator sites — are indexed by Google discussing this trend in the context of Indian fashion and creator content.

**Where it misleads:** This is search-indexed content *about* Instagram, not direct Instagram data. Instagram blocks search engine crawlers, so engagement metrics (views, likes, shares) are inaccessible. A "strong" score means more web articles are writing about the trend — not that reels have high views. Content farms inflate this signal. The weight (0.5×) reflects this: buzz is real information but weakly correlated with value-fashion purchase intent. When buzz is active but demand is weak, the disagreement is itself actionable — it fires the "buzz without demand" override rather than contributing to a buying recommendation.

---

### Source 4 — Google News India (Serper /news endpoint)
**Data class:** Editorial / leading indicator | **Weight: 0.75×**

Query: `{keyword} fashion india`, `gl=in`, **`tbs=qdr:m2` — a strict two-month window.**

Fashion journalism in Indian media (Vogue India, Femina, Myntra/Meesho editorial, retail trade press) precedes mass consumer search by 4–8 weeks. Editorial coverage from the past 8 weeks represents actionable leading signal — content the buyer can still act on before the buying window closes.

**Why the 2-month window specifically:**  
One month (`qdr:m`) misses the full 8-week editorial lead window. Three months (`qdr:m3`) bleeds into the previous season — a June 2026 analysis picking up March editorial written for summer that has already sold through. The 2-month window also self-aligns with India's fashion calendar: in June it captures April–June monsoon editorial building toward July–August consumer demand; in October it captures Diwali ramp-up editorial. The window is seasonally correct by design.

**Where it misleads:** Skews toward English-language Indian media. PR-placed and sponsored editorial inflates this signal. Coverage can be aspirational rather than reflecting actual consumer intent.

---

## 3. Technical design

### Tech stack

| Layer | Technology | Purpose |
|---|---|---|
| UI framework | Streamlit | Web app, session state, sidebar, forms |
| Google Trends | SerpApi (`google_trends` engine) | Consumer search intent — geo=IN, 90-day timeseries |
| Marketplace + Social + News | Serper REST API | Organic search, /news endpoint, gl=in |
| AI synthesis | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) | Structured India-fit check + qualitative signal reasoning |
| Scoring + bet sizing | Pure Python (deterministic) | `score_signal()`, `compute_convergence()`, `compute_bet()` |
| URL parsing | Python `urllib.parse` | Category-page detection on Myntra / Meesho result URLs |
| Config | `python-dotenv` + `st.secrets` | API keys — local `.env` or Streamlit Cloud secrets |
| Test suite | Custom Python runner (`run_tests.py`) | 182 unit tests — scoring, overrides, demo schema, URL logic |
| Demo cache | JSON files (`sample_outputs/`) | Five pre-run analyses; app reviewable with no API keys |
| Feedback log | Append-only JSONL (`feedback_log.jsonl`) | Buyer action logging for future weight recalibration |

### Architecture

```
Buyer names a kurti style to assess
        │
        ▼  [validate_keyword — blocks generic phrases]
┌────────────────────────────────────────────────────┐
│            Four independent signals                │
│  (each cached in st.session_state by keyword)      │
│                                                    │
│  [1] Google Trends India  → direction + evidence   │
│      SerpApi · geo=IN · 90d · auto-broadening      │
│                                                    │
│  [2] Myntra/Meesho catalog → market_health badge   │
│      Serper · 2 queries · category-URL detection   │
│      + 60%+ discount regex · 4-state output        │
│                                                    │
│  [3] Web social (indexed Instagram) → buzz score   │
│      Serper · gl=in                                │
│                                                    │
│  [4] Google News India  → editorial score          │
│      Serper /news · tbs=qdr:m2 · 2-month window   │
│                                                    │
│  Sources vote before Claude sees any of them       │
└────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────┐
│           Weighted convergence scoring           │
│                                                  │
│  Demand group (max 2.5):                         │
│    Google Trends  × 1.5                          │
│    Marketplace    × 1.0                          │
│                                                  │
│  Buzz group (max 2.0):                           │
│    Social signal  × 0.5                          │
│    News coverage  × 0.75                         │
│                                                  │
│  Max total: 4.5  (deliberately uncapped — if     │
│  all sources are strong, the buyer should see    │
│  the full strength of that convergence)          │
└──────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────┐
│  Deterministic override checks (Python only)     │
│  Evaluated before bet sizing — if any fires,     │
│  it overrules the score entirely                 │
│                                                  │
│  1. Hard India-fit fail                          │
│     price_band = "Does not fit" OR               │
│     climate_fit = "No" (for buying horizon)      │
│     → Do not buy — India-fit failure             │
│                                                  │
│  2. Marketplace oversupply + weak demand         │
│     market_health = "oversupply" AND             │
│     Google Trends ≤ 0.5                          │
│     → Do not buy — marketplace oversupply        │
│                                                  │
│  3. Buzz-without-demand                          │
│     buzz_score ≥ 1.0 AND                         │
│     (trends_raw ≤ 0.5 AND market_raw ≤ 0.5)      │
│     → Monitor only — buzz without demand         │
└──────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────┐
│  Claude Haiku synthesis (structured JSON only)   │
│                                                  │
│  Input: all 4 signal results + scores            │
│  Output: india_fit (4 criteria + reasons),       │
│          signal_agreement sentence,              │
│          disagreement_note (null if none),       │
│          bet_reasoning, skepticism_flag          │
│                                                  │
│  Buying horizon passed explicitly: inventory     │
│  bought now will sell during [season] — Claude   │
│  evaluates climate fit for that season, not today│
└──────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────┐
│  Deterministic bet sizing (Python decision tree) │
│                                                  │
│  score ≥ 3.5 + india_fit ≥ 4/4 → Deeper buy     │
│  score ≥ 2.5 + india_fit ≥ 3/4 → Trial buy      │
│  score ≥ 1.5 + india_fit ≥ 2/4 → Small trial    │
│  score ≥ 0.75               → Monitor only      │
│  score < 0.75 OR override   → Do not buy        │
│                                                  │
│  Each bet comes with a bet_logic_tooltip:        │
│  the specific numbers, which threshold fired,    │
│  and what the buyer should watch next            │
└──────────────────────────────────────────────────┘
        │
        ▼
  Buyer-facing output card
  + feedback form (live and demo mode)
```

### Why bet sizing is deterministic Python, not Claude's judgment

If Claude sets the bet size, the recommendation changes unpredictably based on how the model interprets ambiguous signals on a given day. A fixed decision tree with published thresholds means the buyer — and the evaluator — can read the code, understand exactly why "Trial buy" appeared, and override it with store-floor knowledge the tool cannot see. Consistency and auditability matter more than nuance for a buying decision.

### Why Claude Haiku over Sonnet

~$0.003 per query vs ~$0.015. For structured JSON output on a tightly specified prompt (India-fit check, signal agreement, disagreement note, skepticism flag), the quality difference is negligible. Haiku's limitation only matters for open-ended reasoning; a rigid JSON schema with explicit field constraints eliminates that gap.

### Why sources vote before Claude sees them

The convergence score is computed entirely from signal badge text using a deterministic `score_signal()` function. Claude receives the pre-computed scores and override results as inputs — it cannot alter the recommendation tier. This separation means: (a) the scoring logic is auditable without touching the AI layer, and (b) Claude's synthesis is focused on qualitative India-fit assessment where its judgment adds value, not on a numerical weighting task where it might confabulate.

### India-fit check and buying horizon

Claude evaluates four criteria against the *buying horizon* — the season when inventory bought now will actually sell — not the current date. The buying horizon is computed from the current month: June order → sells July–September (monsoon/festive transition). A velvet kurti may be climatically appropriate in February but fails if bought in June when it will land during monsoon. This distinction catches the assignment brief's warning about trends that *"travel visually but fail commercially."*

### Error handling

Every external API call is wrapped in `try/except`. On any source failure, the app returns an "Unavailable" badge for that row and continues with reduced confidence — it never crashes. Each result is cached in `st.session_state` for the session; querying the same keyword twice costs zero additional API calls. Cached demo outputs in `sample_outputs/` ensure the tool is reviewable with no API keys at all.

---

## 4. Evaluation and feedback loop

### How quality was tested

Five demo keywords were chosen deliberately to cover every recommendation tier and verify each override rule fires correctly:

| Keyword | Tier | What is tested |
|---|---|---|
| mirror work kurti | Trial buy | Score 3.0 — convergent demand + healthy marketplace |
| anarkali kurti | Small trial | Score 2.38 — trends rising, social weak |
| mukaish embroidery kurti | Monitor only | Score 1.12 — sparse catalog, no category pages |
| sequin kurti | Do not buy — oversupply | Oversupply override: heavy_disc_count ≥ 2, trends flat |
| chikankari kurti | Monitor — buzz without demand | Buzz override: buzz_score ≥ 1.0, demand ≤ 0.5 |

Each demo was generated from a live API run and saved as JSON. Score reconstruction from stored badge strings is tested in the suite to guarantee demo cards render identically to live analysis cards.

**Failure modes explicitly tested (182 automated tests pass):**
- SerpApi returns no timeline data → graceful "Unavailable", app continues on three sources
- Google Trends broadening: compound keyword near-zero → retries and discloses broader keyword used
- Serper returning no organic results → "Not found in marketplace", score contribution = 0
- Claude returning malformed JSON or timing out → safe defaults applied, no crash, buyer sees signal rows
- Oversupply override with flat trends → confirmed fires; does not fire when trends are rising (suppliers entering a growing market)
- Buzz-without-demand override → confirmed requires both social AND news active (buzz_score ≥ 1.0 = minimum 0.5 + 0.75), not just one
- India-fit hard fail takes priority over oversupply override
- Generic keyword inputs ("women kurtis", "buy kurtis online") → blocked with a specific error message and style examples
- Any keyword other than women kurti category is not analyzed and shown an aprropriate error message and nudge to enter what can be analyzed


### In-app feedback loop

After every analysis (live or demo), the buyer sees a four-option feedback form:

> *Will monitor / Buying / ordering / Decided not to buy / Signal seems wrong*

Submissions are appended to `feedback_log.jsonl` with timestamp, keyword, recommendation, action taken, and an optional note. Live analyses and demo interactions are logged separately (`"source": "demo"`).

**What this enables in a production version:** After each buying cycle, the buyer inputs actual sell-through percentage. The system knows which source was correct for that trend and category. After 10–15 buying cycles, source weights recalibrate against this specific retailer's sell-through history. The current weights (Trends 1.5×, Marketplace 1.0×, News 0.75×, Social 0.5×) reflect prior knowledge from the brief's own signal reliability warnings. Production weights would be calibrated against observed sell-through data.

---

## 5. Business measurement

**Markdown reduction:** A buyer who avoids one wrong deep-buy of 400 units at ₹849 saves approximately ₹34,000 in end-of-season markdown, assuming 40% markdown on 100 units that don't sell at full price. The oversupply detection specifically targets this — it flags when catalog presence is propped up by liquidation discounting, not genuine demand.

**Stockout avoidance:** Catching a rising trend 6–8 weeks earlier (when Google Trends shows a steady climb but sales data is flat) secures supplier slots before competitors. For a value-fashion retailer at ₹399–₹1,499, supplier relationship and lead time are typically the binding constraint on a buying decision, not product concept.

**Decision speed:** The tool converts a 2-hour scattered research task — WhatsApp group checks, Instagram browsing, manual Meesho scrolling, competitor catalog review — into a 12-second structured output. The buyer arrives at a category review meeting with citable evidence and a specific recommendation, not instinct.

**Buyer adoption:** The tool shows its complete reasoning — signal sources, individual scores, override logic, disagreement notes, skepticism flag. Buyers can override any individual signal using store-floor knowledge the tool cannot access (local cluster preferences, specific supplier relationships, past seasonal patterns). A tool that shows its work gets used; a black box gets ignored and cited as cover.

**What success looks like quantitatively:**
- Sell-through on tool-recommended trial buys exceeds category baseline by ≥10 percentage points over 3 cycles
- Markdown rate on "Monitor only" categories the buyer correctly held back shows measurable reduction
- Time from trend identification to buying decision drops from days to under an hour

---

## 6. What I would build next

**Store-floor memory (highest priority).** Let buyers log why similar bets worked or failed last season — notes like "our Lucknow cluster customer won't buy heavily embroidered kurtis above ₹799" or "palazzo silhouettes always arrive 6 weeks late in Tier 2." The tool learns from this specific retailer's customer base, not generalised signals. This is the "store notes" angle from the brief and is the one feature that would most directly convert the tool from a generic signal aggregator into a proprietary buying advantage.

**Feedback loop calibration.** Connect sell-through data to source weight recalibration. After 15 buying cycles the tool should know whether this retailer's Google Trends signal leads by 5 weeks or 9 weeks — and tighten thresholds accordingly.

**Competitor buy map.** Track when Reliance Trends, V-Mart, or Shein India launch a specific style — not Myntra/Meesho broadly, but competitor first-mover timing. Knowing a direct competitor launched 3 weeks ago tells the buyer whether the window is still open or already closing.

**Real social signal.** Replace the web-indexed social proxy with direct creator data — Apify's Instagram scraper for actual engagement metrics on kurti styling content. Genuine haul-video view counts and engagement rates rather than inferring from blog articles about Instagram content.

**Dual news window.** Run two parallel news queries — `qdr:m` and `qdr:m2` — and treat agreement between both windows as a stronger editorial signal than either alone. A trend covered in both the last 4 weeks and the last 8 weeks has sustained build-up, not a single article spike.

---

## Source transparency

| Source | API | Key required | Weight | Primary limitation |
|---|---|---|---|---|
| Google Trends India | SerpApi | `SERPAPI_KEY` | 1.5× | Data-sparse for compound niche keywords; auto-broadening applied |
| Myntra/Meesho catalog + price health | Serper | `SERPER_API_KEY` | 1.0× | Snippet-indexed, not live catalog; sponsored listings inflate counts |
| Web social signal | Serper | `SERPER_API_KEY` | 0.5× | Google-indexed content about Instagram — no direct engagement data |
| Google News India | Serper /news | `SERPER_API_KEY` | 0.75× | English-language media only; PR/sponsored editorial inflates signal |
| India-fit synthesis | Anthropic (Claude Haiku) | `ANTHROPIC_API_KEY` | — | Qualitative judgment on structured inputs; not used for bet sizing |

Three of four signal sources use a single Serper API key. One additional SerpApi key for Google Trends. Claude Haiku for structured synthesis only — all scoring and recommendation logic is deterministic Python.


