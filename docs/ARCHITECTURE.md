# Architecture

Source of truth for contracts in the new repo. Change contracts here first, then in code.

## Principles

1. **Raw is immutable.** Every fetch is saved exactly as received, before parsing.
   Everything downstream can be rebuilt from raw.
2. **Point-in-time everywhere.** Every row is "what was knowable at time t":
   universe membership, fundamentals (by filing date), ticker ↔ company mapping.
3. **Writes fail closed.** Keyed, idempotent writes. A write that would shrink history
   is an error, not a refresh.
4. **One permanent ID per security.** Tickers get reused and renamed; `security_id`
   never changes.
5. **Pure functions except in `ingest/` and `pipelines/`.** Features, labels, models
   and evaluation take dataframes and return dataframes.
6. **Research outputs never overwrite production artifacts.**
7. **Public code, private state.** The repo holds code, docs and synthetic fixtures only.
   Data, models, live configs and every secret live outside it (`SECURITY.md`).
8. **Orders only through the risk engine** (`EXECUTION_AND_RISK.md`).

## Repo layout

```
us-equity-trading/            # PUBLIC
  CLAUDE.md
  README.md
  pyproject.toml              # pinned deps: pandas, numpy, pyarrow, duckdb, scikit-learn,
                              # xgboost, requests, pyyaml, pytest; dev: pre-commit, pip-audit
  .gitignore  .pre-commit-config.yaml  .env.example   # see SECURITY.md
  docs/
    PLAN.md  ARCHITECTURE.md  DATA_SOURCES.md  EVALUATION_PROTOCOL.md
    SECURITY.md  EXECUTION_AND_RISK.md
    decision_log.md           # dated decisions and anything that changes a contract
    preregistration/          # one file per pre-registered test, written before results
    research/                 # research write-ups
  config/
    secrets.py                # env-only key loading, redacting repr, log redaction filter
    market_calendar.py        # NYSE sessions, holidays, early closes (from configs/nyse_calendar.yaml)
  configs/                    # public *.example.yaml only; live configs load from the private repo
    nyse_calendar.yaml        # public NYSE holidays + early closes (source: nyse.com)
    sources.yaml              # endpoints, rate limits, key env var names
    universe.yaml             # universe definition, window start, liquidity floor
    costs.yaml                # spread/fee model (see EVALUATION_PROTOCOL)
    features.yaml             # active feature list (must exist in the registry)
    model.yaml                # model + walk-forward params
  contracts/
    schema.py                 # column specs + validators for every table below
    registries.py             # FEATURE_REGISTRY, LABEL_REGISTRY
  ingest/
    http.py                   # one rate-limited, retrying client; writes raw archive
    raw_archive.py            # raw/<source>/<yyyy>/<mm>/<dd>/<request_hash>.json.gz
    sources/
      massive.py  stooq.py  tiingo.py  wiki_prices.py  yahoo.py
      sec_edgar.py  fred.py  nasdaq_symdir.py  sp500_membership.py
      finra_short.py  french_factors.py  openfigi.py
  build/
    security_master.py        # security_id, CIK, FIGI, ticker validity ranges
    prices.py                 # multi-source reconcile -> canonical unadjusted OHLCV
    corporate_actions.py      # splits, dividends -> adjustment factors, total returns
    universe.py               # point-in-time membership per date
    delistings.py             # exit reason + delisting return
    coverage.py               # coverage report + gate
  features/                   # one module per family; all pure
  labels/                     # forward returns, lagged by entry convention
  models/                     # rank-target regressor, ranker, linear baseline
  evaluation/
    walk_forward.py           # rolling folds, embargo, purge (port from NEPSE)
    metrics.py                # daily rank IC, t-stat, top-k excess, turnover, n_eff
    baselines.py              # momentum 12-1, reversal 1m, low vol, equal weight, SPY
    costs.py                  # per-side cost from costs.yaml
    backtest.py               # top-k portfolio, rebalancing, costs, lag
    attribution.py            # regression on French factors
    variant_registry.py       # every config tried, for best-of-N correction
  pipelines/
    daily_collect.py          # forward collector (GitHub Actions)
    bronze.py                 # keyed, idempotent, never-shrinking bronze parquet writes
    build_dataset.py          # raw -> bronze -> silver -> gold
    run_research.py           # bake-off / backtests from a config
    score_shadow.py           # daily shadow scores, first-write-wins
    trade_daily.py            # score -> target -> intents -> risk -> broker -> reconcile
  execution/
    broker.py                 # BrokerAdapter interface + OrderIntent/Fill types
    sim_broker.py             # backtests and tests
    alpaca.py                 # paper|live via REST (requests), separate hosts and keys
    risk.py                   # hard limits + kill switch; the strategy cannot bypass it
    reconcile.py              # intents vs fills vs positions
  tests/
  .github/workflows/
    collect.yml               # cron: daily collector
    tests.yml                 # pytest + gitleaks + pip-audit on push/PR (no secrets)
    codeql.yml
  data/                       # gitignored; see "Storage"
```

## Data layers

| Layer | Path | Content | Mutability |
|---|---|---|---|
| raw | `data/raw/<source>/<yyyy>/<mm>/<dd>/` | exact API responses, gzipped, with request metadata | append-only, never edited |
| bronze | `data/bronze/<source>/*.parquet` | parsed per source, typed, no cross-source logic | rebuildable |
| silver | `data/silver/*.parquet` | reconciled canonical tables (below) | rebuildable, versioned |
| gold | `data/gold/<dataset_version>/` | features + labels for one config | rebuildable |
| research | `data/research/<study>/` | OOF scores, summaries | per study |
| shadow | `data/shadow/shadow_log.parquet` | daily scores, first-write-wins | append-only |

## Bronze tables (per source, Phase 1)

Parsed from raw, typed, no cross-source logic. One file per partition; a rewrite must
keep every existing key (a shrink raises).

**massive_grouped** `data/bronze/massive_grouped/date=<d>.parquet`: `date`, `ticker`,
`open`, `high`, `low`, `close`, `volume`, `vwap`, `n_trades`, `otc`. Key (`date`, `ticker`).

**nasdaq_symdir** `data/bronze/nasdaq_symdir/snapshot=<d>.parquet`: `snapshot_date`,
`file_created` (UTC), `list_file` (nasdaqlisted / otherlisted), `symbol`,
`security_name`, `exchange`, `etf`, `test_issue`, `round_lot`. Key (`list_file`, `symbol`).

**fred** `data/bronze/fred/fetch=<d>.parquet`: `date`, `series`, `value` (NaN when FRED
reports "."), `vintage` (= realtime_start). Key (`series`, `date`, `vintage`).

**sp500_membership** `data/bronze/sp500_membership/fetch=<d>.parquet`: latest snapshot
per source: `source`, `date`, `ticker`. Key (`source`, `date`, `ticker`).

## Canonical tables (silver)

**security_master**: `security_id` (str, permanent), `cik`, `figi`, `name`,
`security_type` (common / ADR / ETF / …), `exchange`, `first_seen`, `last_seen`.

**ticker_history**: `security_id`, `ticker`, `valid_from`, `valid_to`.

**prices_daily**: `date`, `security_id`, `open`, `high`, `low`, `close`
(unadjusted), `volume`, `dollar_volume`, `n_sources`, `agree_flag`, `primary_source`,
`flags` (single_source, jump_unexplained, stale).

**corporate_actions**: `security_id`, `ex_date`, `action` (split / cash_dividend /
spinoff), `value`, `source`, `n_sources`.

**total_return_daily**: `date`, `security_id`, `ret_1d` (includes dividends and
splits), `adj_factor`.

**universe_membership**: `date`, `security_id`, `in_sp500` (bool), `source_agree`.

**delistings**: `security_id`, `last_date`, `reason` (acquired / bankrupt /
moved / unknown), `delisting_return`, `observed` (bool).

**fundamentals_pit**: `security_id`, `concept`, `value`, `period_end`, `filed`,
`available_from` (= next trading day after `filed`).

**macro_daily**: `date`, `series`, `value`, `vintage`.

Every table has a validator in `contracts/schema.py`: required columns, dtypes,
key uniqueness and "no future `available_from`" checks.

## Time conventions

- Store dates in exchange time (America/New_York). Store timestamps in UTC.
- A US session closes at 16:00 ET = **01:45 NPT** (EDT) / **02:45 NPT** (EST).
- A decision made from the data of session *d* executes at the **open of d+1**
  (primary convention) or the close of d+1 (conservative variant). Never at the close
  of d. See `EVALUATION_PROTOCOL.md`.

## Scheduling (why not your laptop)

The laptop sleeps overnight, which is exactly when US data lands. Run the collector
on **GitHub Actions**:

- `collect.yml`, cron `30 23 * * 1-5` (UTC), about 3.5 hours after the close. Retry cron at
  `0 11 * * 2-6` catches late publishes. Both are idempotent.
- Holidays: the job checks the market calendar and exits cleanly with "no session".
- Free minutes: unlimited on public repos; 2,000 min/month on private repos (the job
  needs about 2 min/day).
- On failure: open a GitHub issue automatically, or notify Telegram if configured.

## Storage

| Store | Visibility | Holds |
|---|---|---|
| `us-equity-trading` | public | code, docs, synthetic fixtures, `*.example.yaml` |
| `us-equity-data` | private | raw archive, bronze/silver parquet (vendor terms forbid redistribution) |
| `us-equity-private` | private | trained models, frozen live configs, pre-registration artifacts hashes |
| GitHub Actions secrets | private | data API keys, the data-repo token, paper broker keys |
| client host secret store | client-only | the client's broker keys; never leaves that host |

- The collector commits daily parquet (~0.3–1 MB/day) to `us-equity-data` using a
  fine-grained token scoped to that repo only. Move to Backblaze B2 / Cloudflare R2
  free tiers past ~1 GB.
- Locally: DuckDB over parquet. No database server.
- Client execution logs and trade history live in each client's own deployment (SQLite
  there), never in any of these repos.

## Porting from NEPSE (copy, don't import)

Copy these pure pieces, then adapt and re-test:

- `models/train_xgb.py`: `_walk_forward_folds`, `_purge_boundary_rows`
- `models/train_ranker.py`: `build_relevance`, `prepare_ranking_data`, `_daily_rank_ic`
- `scripts/research/algo_bakeoff.py`: the bake-off harness
- `scripts/research/variant_registry.py`: the idea, not the NEPSE paths
- The fail-closed write pattern and first-write-wins shadow log

Do **not** copy: day runner, scrapers, dashboard, Docker, agent, NEPSE calendar, costs.

Once both systems are stable (after the NEPSE holdout, ~2027-03), extract the
common pieces into a shared package (`quantcore`) that both import.
