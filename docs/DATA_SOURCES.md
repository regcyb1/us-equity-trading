# Data sources — free, and made reliable by reconciliation

Limits were checked on 2026-09-30 from public pages and third-party summaries.
**Re-verify every limit at signup** and record what you saw in `docs/decision_log.md`.
Free tiers change without notice; the design below assumes any single source can
disappear.

## The core problem

No free source gives all three of: long history, full coverage including delisted
stocks (survivorship-free), and reliable corporate-action adjustments. The plan
therefore:

1. uses **several sources per data type**, each for what it is good at;
2. stores the **raw response** of every fetch, immutable, before any parsing;
3. **reconciles** sources into one canonical table, recording agreement per row;
4. **measures coverage** against a point-in-time universe and trims the test window
   to where coverage is proven, instead of assuming it;
5. **collects forward from day one**, because forward data is survivorship-free by
   construction.

## Source catalogue

Reliability tiers: **A** = official or regulator; **B** = established vendor with a
documented free API; **C** = unofficial or community, used only as a cross-check or
gap fill.

### Prices (daily OHLCV)

| Source | Tier | Free access (verify) | Good for | Weakness |
|---|---|---|---|---|
| **Massive** (formerly Polygon.io), Stocks Basic | B | $0; 5 calls/min; end-of-day; ~2 years history | **Grouped daily**: the whole US market for one date in one call, delisted names included. Survivorship-free truth for the last 2 years and the **primary forward feed** (1 call/day). Splits/dividends reference endpoints. | Only ~2 years back. |
| **Stooq** bulk + per-symbol CSV | C | Free; API key via CAPTCHA since early 2026; daily hit limit | Long history for currently listed names; bulk ZIP snapshots of the whole database | Unofficial; delisted coverage patchy; adjustment method undocumented |
| **Tiingo**, free plan | B | 500 unique symbols/month, 50 req/hour, 1,000 req/day | Clean EOD with raw + adjusted fields and dividend/split factors; covers many delisted tickers. Use to **fill delisted members** over several months (500 new symbols each month). | Symbol cap makes a full backfill take months. $10/month removes the cap if you ever relax the free-only rule. |
| **Nasdaq Data Link WIKI Prices** | B (frozen) | Free, frozen at 2018-04 | ~3,000 US companies **including later-delisted ones**, with splits and dividends, up to 2018 | No data after April 2018; community-maintained; known errors. Cross-check only. |
| **Yahoo Finance via yfinance** | C | Unofficial; undocumented rate limits, IP blocks | Quick cross-check of recent closes and actions | Not an API; breaks under load; no delisted names. **Never a primary source.** |

### Universe and identity

| Source | Tier | Use |
|---|---|---|
| **fja05680/sp500** (GitHub) | C | Point-in-time S&P 500 membership since 1996, updated 2026-07. Primary membership history. |
| **hanshof/sp500_constituents** (GitHub) | C | Second membership history. Reconcile with fja05680. |
| **Wikipedia "List of S&P 500 companies"** changes table | C | Third cross-check for add/remove dates. |
| **Nasdaq Trader Symbol Directory** (`nasdaqlisted.txt`, `otherlisted.txt` under `nasdaqtrader.com/dynamic/SymDir/`) | A | Today's full list of listed securities with ETF/test-issue flags. **Snapshot daily from day one**: this builds your own point-in-time listing history. |
| **SEC `company_tickers.json`** + submissions API | A | Ticker → CIK (current). CIK is the permanent company ID. |
| **OpenFIGI** API | B | Free ticker → FIGI mapping, higher limits with a free key. Helps with renamed and reused tickers. |

### Fundamentals and events (all SEC, tier A)

- `data.sec.gov` **companyfacts** (XBRL): every reported value with its `filed` date,
  so fundamentals can be made point-in-time. Use the value only from `filed + 1`
  trading day.
- **Submissions** API: the filing history. 8-K item 2.02 filing timestamps give
  **earnings-announcement dates** for free.
- **Form 4**: insider transactions. **13F**: institutional holdings (45-day lag, so a slow signal).
- Financial Statement Data Sets: quarterly bulk ZIPs, for backfill without API calls.
- **Rules:** at most 10 requests/second, a `User-Agent` header with a name and contact
  email, no crawling. Violations lead to temporary IP blocks.

### Market structure (FINRA, tier A)

- **Daily short-sale volume** files (Reg SHO), free, per symbol per day.
- **Short interest**, twice monthly, free.

### Macro and regime (tier A)

- **FRED**, with a free API key: `DGS10`, `DGS2`, `T10Y2Y`, `DFF`, `VIXCLS`,
  `BAMLH0A0HYM2` (high-yield spread). Use **ALFRED** vintages for any series that
  gets revised.
- **U.S. Treasury** daily yield curve, as a cross-check for FRED.

### Benchmarks and attribution

- **Kenneth French Data Library**: free daily factor returns (market, SMB, HML, RMW,
  CMA, momentum). Used to check whether a "signal" is a known factor in disguise.
- **SPY** from the price sources above: the buy-and-hold benchmark.

## How they combine (the reliability recipe)

### Prices, historical (2005 → today − 2y)
1. Universe = point-in-time S&P 500 members (fja05680, reconciled against hanshof).
2. For each member-day, collect closes from Stooq, Tiingo, WIKI (≤2018) and Yahoo,
   whichever have it.
3. Canonical close = the median of the sources that agree within 0.5%. Record
   `n_sources` and `agree_flag`. A single-source value is flagged `single_source`.
4. Corporate actions: keep **unadjusted** prices plus a separate actions table
   (splits and dividends from Tiingo and Massive). Compute total returns yourself,
   then cross-check against each source's adjusted close. A jump of more than 40%
   with no action explaining it is flagged for review, never silently kept.

### Prices, recent (last 2 years) and forward
- Massive grouped daily is primary (complete market, delisted names included).
  Stooq and Yahoo are cross-checks. Disagreements go to the same reconciliation.

### Delistings
- A member that leaves the index or stops trading needs a **delisting return**:
  - acquisition → the last trade (or the deal price) is the exit;
  - bankruptcy or forced delisting with no final price → assume **−30%** from the
    last close (the conventional research default) and flag it.
- Report how many delisting returns were assumed rather than observed.

### Coverage gate (must pass before any modelling)
- Member-day coverage (a valid canonical close exists) **≥ 99%** over the chosen
  window. If early years fail, **start the window later**. Do not fill gaps.
- Two-source agreement on **≥ 95%** of member-days.
- Every missing member is listed with its exit reason, because the direction of the
  bias matters: missing bankruptcies inflate returns.

## Free-tier budget (initial backfill)

| Job | Calls | Time at free limits |
|---|---|---|
| Massive grouped daily, 2 years | ~504 | ~2 hours at 5/min |
| Tiingo delisted members | ~1,000 names | ~2 months at 500 names/month; start in week 1 |
| Stooq bulk | a few ZIPs | minutes, within the daily hit limit |
| SEC companyfacts, ~1,000 CIKs | ~1,000 | ~2 minutes at ≤10/s (use ~5/s) |
| FRED, ~10 series | ~10 | seconds |

The daily forward job needs about 5 calls in total.

## Licensing and the public repo

Most vendor terms (Massive, Tiingo, Stooq, Yahoo) forbid redistributing their data.
The code repo is public, so **no raw or derived vendor data is ever committed there**.
Data lives in the private data repo or bucket. Public docs show aggregates only
(coverage percentages, IC tables), never price rows. Official US government data
(SEC, FRED, Treasury, FINRA) is generally public, but keep it in the private store too
for one consistent rule.

## Sources deliberately excluded
- Alpha Vantage free tier (about 25 requests/day: too small).
- Scraping any site whose terms forbid it.
- Paid survivorship-free databases (Norgate, CRSP, Sharadar). Revisit only if the
  coverage gate fails and you relax the free-only rule. Sharadar via Nasdaq Data
  Link is the cheapest serious option.
