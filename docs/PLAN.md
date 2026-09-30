# Build plan

The timeline assumes evenings and weekends (~10 h/week). Each phase ends with a
**gate**. Don't start the next phase until the gate passes, or until the decision log
says why it was skipped.

```
P0 foundation + security → P1 forward collector → P2 historical data → P3 features/labels
→ P4 baselines + models → P5 portfolio backtest → P6 paper trading + holdout
→ P7 live execution for clients → P8 product + scale
```

## Phase 0 — Foundation and security (week 1)

**Tasks**
- [ ] Repos: `us-equity-trading` (public), `us-equity-data` (private), `us-equity-private` (private).
- [ ] Copy `CLAUDE.md` to the root and the other docs to `docs/`. Start `docs/decision_log.md`.
- [ ] Security baseline from `SECURITY.md` §2–4: `.gitignore`, pre-commit (gitleaks,
      block-data-files), push protection, branch protection, the CI gitleaks job,
      Dependabot, CodeQL, pip-audit.
- [ ] `config/secrets.py`: env-only key loading, redacting `repr`, a log redaction filter.
- [ ] Python 3.11 + `pyproject.toml` with pinned deps (see `ARCHITECTURE.md`).
- [ ] `contracts/schema.py` validators; empty `FEATURE_REGISTRY`.
- [ ] `ingest/http.py`: rate limit, retry with backoff, timeouts, TLS on, raw-archive write.
- [ ] `tests.yml` CI with explicit `permissions: contents: read`.
- [ ] Sign up: Massive, Tiingo, FRED, Stooq key, OpenFIGI, Alpaca **paper**. Keys go into
      GitHub secrets + `.env` only. Log the free-tier limits you saw (not the keys).

**Gate:** CI green + the security gate in `SECURITY.md` §5 fully checked.

## Phase 1 — Forward collector, live from week 1 (weeks 1–2)

The most time-sensitive phase: clean data only accumulates once this starts.

- [ ] `nasdaq_symdir.py`: a daily snapshot of `nasdaqlisted.txt` + `otherlisted.txt`.
- [ ] `massive.py`: grouped daily for the last session (1 call).
- [ ] `fred.py`: macro series; `sp500_membership.py`: weekly pull + diff of both membership files.
- [ ] NYSE holiday calendar CSV, plus a check that "0 rows returned" happens only on a holiday.
- [ ] `pipelines/daily_collect.py`: idempotent; commits to `us-equity-data` with a repo-scoped token.
- [ ] `collect.yml`: main cron + retry cron; logs show counts only; opens a (non-sensitive) issue on failure.
- [ ] Integrity check: rows vs yesterday ±5%, no duplicate keys, close > 0.

**Gate:** 10 consecutive trading days collected with no manual help, one holiday
handled, one injected failure alerted, and the public Actions logs contain no data values.

## Phase 2 — Historical dataset (weeks 2–6)

- [ ] `security_master` + `ticker_history` (SEC tickers, OpenFIGI, membership files).
- [ ] Price backfill: Stooq bulk; Massive for 2 years (~504 calls); WIKI to 2018;
      Tiingo for delisted members (500 names/month, **start in week 2**); Yahoo only as
      a cross-check.
- [ ] `build/prices.py` reconcile (median of agreeing sources, `n_sources`, flags).
- [ ] `build/corporate_actions.py` → total returns; flag unexplained jumps > 40%.
- [ ] `build/delistings.py`; `build/coverage.py` → the coverage report (aggregates only
      in the public docs).
- [ ] SEC companyfacts → `fundamentals_pit` (≤5 req/s, User-Agent set).

**Gate:** coverage ≥ 99% and two-source agreement ≥ 95% over the window; jumps
resolved; delistings reviewed. If the early years fail, start the window later.
**Never fill gaps.**

## Phase 3 — Features and labels (weeks 6–8)

- [ ] Labels: forward total return over 1/5/20 sessions **from the d+1 open**, plus rank versions.
- [ ] Feature families (register each first): price/momentum/volatility, liquidity,
      cross-sectional and sector ranks, market/macro, PIT fundamentals (value,
      profitability, accruals, asset growth), earnings events (8-K 2.02, post-earnings
      drift), FINRA short interest and short volume.
- [ ] Leakage tests: shift-by-one, `available_from` checks, label-shuffle control.

**Gate:** leakage tests pass; no feature family is more than 20% missing.

## Phase 4 — Baselines, then models (weeks 8–10)

- [ ] Baselines through the full protocol: equal weight, SPY, 12-1 momentum, 1-month
      reversal, low volatility, a value composite.
- [ ] Bake-off (ported from NEPSE `algo_bakeoff.py`): ridge on ranks, XGB regressor on a
      rank target, HistGBM, XGB ranker, a small MLP, a rank-average ensemble. Horizons 5
      and 20 (1 as a reference only).
- [ ] Factor attribution; every variant logged.

**Gate:** all 6 acceptance conditions in `EVALUATION_PROTOCOL.md`.

**Kill criteria (fixed now):**
- Model ≤ best baseline net of stress costs at lag 1 → stop modelling. Trade the best
  baseline as the product (a disciplined factor strategy is still sellable to clients),
  or pivot the universe to mid caps.
- Alpha t < 2 after factor attribution → same decision.
- No 8+ year window meets the coverage gate → shorter window with a caveat, or relax
  free-only (Tiingo $10/month or Sharadar).

## Phase 5 — Portfolio backtest (weeks 10–11)

- [ ] Top-k long-only, equal weight; weekly and monthly rebalance; buffer rule (hold
      until rank > 1.5k).
- [ ] `SimBroker` runs the same `OrderIntent` → risk engine path that live will use.
- [ ] Full metric table at base and stress costs.
- [ ] Open the **historical vault** once; record the result in the decision log.

## Phase 6 — Paper trading and forward holdout (week 11 → +6 months)

- [ ] `BrokerAdapter` + `AlpacaBroker(mode=paper)` + the risk engine + the kill switch
      (`EXECUTION_AND_RISK.md`).
- [ ] Commit `docs/preregistration/forward_holdout_v1.md` **before** the first paper order.
- [ ] Daily: collect → score → risk-check → submit before the open → reconcile fills.
- [ ] 120 sessions with no retrain or retune. Monthly check-ins cover health only.

**Gate:** the pre-registered metric passes, **and** the execution gate items 2–5 in
`EXECUTION_AND_RISK.md` pass.

## Phase 7 — Live execution for clients (after Phase 6 passes)

- [ ] Per-client deployment template (VPS/container, the client's own secrets, tagged release).
- [ ] Client onboarding checklist (`EXECUTION_AND_RISK.md`): legal structure, limits
      signed off, paper period on the client's own paper account, 25% size in month one.
- [ ] Private daily client report.
- [ ] `IbkrBroker` only if a client needs IBKR.

**Gate:** execution gate item 6, plus one month live at 25% size with no risk
incident, before full size.

## Phase 8 — Product and scale

- A static HTML status page (holdout progress, data health, aggregate metrics only).
- Extract a shared `quantcore` package with NEPSE (after ~2027-03).
- Second universe (mid caps) or second market, each with its own gate and holdout.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Secret leaked in the public repo | medium | pre-commit + CI gitleaks + push protection + env-only secrets; rotation playbook |
| Vendor data published publicly (terms breach) | medium | data files blocked by hooks; data only in the private repo |
| Free tier shrinks or disappears | medium | raw archive, multiple sources, 1 call/day forward |
| Survivorship gap pre-2018 | high | coverage gate, trimmed window, flagged assumed delisting returns |
| No edge beyond known factors | **high** | baselines first, kill criteria, factor attribution |
| Overfitting | medium | variant registry, deflated Sharpe, vault + forward holdout |
| Execution bug trades real money wrongly | medium | independent risk engine, kill switch, paper period, 25% ramp |
| Regulatory exposure with clients | medium | legal advice in the client's jurisdiction before the first paid client |
| Scope creep | high | phases locked behind gates |

## Definition of done for v1

One frozen strategy with: coverage proven, the protocol table complete, baselines
beaten (or honestly not), the vault opened once, a 120-session paper holdout passed,
execution gate passed, and a clean security gate. v1 is done when the answer is
trustworthy and the system can run a client account safely.
