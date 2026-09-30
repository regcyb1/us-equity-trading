# Evaluation protocol

Every result must follow these rules before anyone believes it. Most of them exist
because the NEPSE system broke them once and produced a number that later
collapsed. The "why" column records what happened there.

## Rules

| # | Rule | Why (NEPSE lesson) |
|---|---|---|
| E1 | **Entry lag ≥ 1.** Decide on session *d* data, execute at the open of *d+1* (primary) or the close of *d+1* (conservative). Report both. | Lag 0 turned a −1.04% strategy into +2.35%. In the 2026-09-30 bake-off, lag 1 removed about ⅔ of the rank IC for every model. |
| E2 | **Point-in-time universe.** Membership as of each date. No "today's S&P 500 backtested to 2005". | Survivorship inflates returns; the direction of the bias is known and always flattering. |
| E3 | **Point-in-time fundamentals.** Use a value only from the trading day after its `filed` date. | A leak of even a few days shows up as fake skill. |
| E4 | **Delisting returns included** (observed or assumed −30%, flagged). | Dropping dead stocks removes the worst outcomes. |
| E5 | **Costs always**, from `configs/costs.yaml`, per side, by liquidity bucket. Report gross and net. | A 1-session NEPSE edge of +0.94% gross was dead after about 1% round-trip cost. |
| E6 | **Walk-forward only**: rolling training window, embargo ≥ label horizon, purge at the boundary. Never random K-fold. | Overlapping forward returns leak across a random split. |
| E7 | **Rank metrics, not accuracy.** Headline = daily rank IC and top-k excess return net of costs. Never quote directional accuracy. If it appears anywhere, its base rate sits beside it. | The NEPSE "60% accuracy" was mostly the base rate. |
| E8 | **Beat the baselines, not zero.** A model is compared with the best simple factor on the same dates, lag and costs. | Much of NEPSE's lag-0 IC was plain 3-day reversal. |
| E9 | **Factor attribution.** Regress strategy returns on the French factors (MKT, SMB, HML, RMW, CMA, MOM). Report the alpha and its t-stat. | A "signal" that is just momentum is not new edge. |
| E10 | **Count every variant** in `variant_registry`. Correct the best result for selection (deflated Sharpe, or a null best-of-N simulation). | 566 NEPSE variants: best-of-N alone could explain about 5 pp of lift. |
| E11 | **Independent samples.** Report `n_eff` = number of non-overlapping holding periods. Require n_eff ≥ 60 for any acceptance. | Overlapping 20-day returns look like thousands of samples but are not. |
| E12 | **Out-of-fold only.** In-sample predictions never appear in a report. | NEPSE `preds.parquet` was in-sample and showed a fake 76% hit rate. |
| E13 | **Unclipped returns for evaluation.** Training may clip; evaluation may not. | The profit and loss sits in the tails that clipping removes. |
| E14 | **Two vaults.** (a) Historical vault: the last 12 months of history are untouched until the final candidate is chosen; open it once. (b) Forward holdout: pre-registered, 120 sessions, starts after the vault result. | Every in-sample-era period gets seen during selection. Only unseen data is a test. |
| E15 | **Pre-register before running** any test that decides something: hypothesis, metric, threshold, n_eff, and what failure means. Commit it before the results. | Stops moving the goalposts. |
| E16 | **Paper equals backtest.** During paper trading, replay the same days through `SimBroker`. Positions must match, and realised slippage must sit inside the stress-cost assumption. | A backtest that can't be reproduced by the live path is not evidence. |
| E17 | **Public reports show aggregates only.** No price rows, positions or client figures in the public repo. | Vendor terms and client confidentiality (`SECURITY.md`). |

## Cost model v1 (`configs/costs.yaml`)

| Component | Value | Note |
|---|---|---|
| Commission | 0 | Most US retail brokers |
| SEC Section 31 fee | $20.60 per $1M of **sales** | Rate effective 2026-04-04; SEC resets it each fiscal year, so re-check |
| FINRA TAF | per-share fee on sales, capped per trade | small; take the current rate from FINRA |
| Half-spread + slippage, S&P 500 | **5 bps per side** base, **10 bps** stress | Conservative for mega caps, fair for the smallest members |
| Taxes | not modelled | depends on jurisdiction; report pre-tax |

Round trip ≈ 10 bps base and 20 bps stress. Every result is reported at both.

## Metrics, reported in one table per claim

Pool · entry lag · horizon · rebalance frequency · holding · costs (base and stress) ·
daily rank IC (mean, t, % positive days) · top-k minus universe, gross and net ·
annual turnover · net Sharpe · max drawdown · n_eff · factor alpha (t) · best baseline
on the same rows · number of variants tried.

A claim missing any cell is not finished.

## Acceptance gate for a research candidate (all must hold)

1. Coverage gate passed for the evaluation window (`DATA_SOURCES.md`).
2. Lag-1, net of **stress** costs: top-k Sharpe > equal-weight universe Sharpe and >
   the best single baseline, across the full walk-forward.
3. Positive in ≥ 4 of 5 folds.
4. Factor alpha t-stat ≥ 2 after E10's selection correction.
5. n_eff ≥ 60.
6. Label-shuffle control: the same pipeline on shuffled labels gives IC ≈ 0
   (|IC| < 0.005). This proves there is no leak.

Pass → open the historical vault once → if it holds, pre-register the forward holdout.
Fail → see the kill criteria in `PLAN.md`.

## Pre-registration template (`docs/preregistration/<name>.md`)

```
Name / date written / author
Hypothesis (one sentence)
Frozen artifact: model hash, config hash, feature list hash
Universe, lag, horizon, rebalance, cost scenario
Primary metric + threshold for pass
Secondary metrics (reported, not decisive)
Sample: start date, number of sessions, n_eff expected
Stop rules: what ends the test early (data outage > N days, etc.)
What pass means / what fail means (actions, written now)
```
