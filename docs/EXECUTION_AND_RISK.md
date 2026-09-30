# Execution and risk

Execution is the last thing built and the first thing that can lose real money.
Every rule here is enforced in code by a **risk engine that the strategy cannot
bypass**.

## Broker choice

| Broker | Use | Why |
|---|---|---|
| **Alpaca**, paper | all development and your own paper holdout | Free, global sign-up by email, no brokerage account needed, REST API, commission-free. Paper (`paper-api.alpaca.markets`) and live (`api.alpaca.markets`) are separate hosts with separate keys. |
| **Alpaca**, live | clients who hold Alpaca accounts | Same code path as paper; only the host and keys change. |
| **Interactive Brokers** | clients who already use IBKR (common internationally) | Global access, broad markets. Its API is harder (Client Portal / TWS), so build the adapter only when a client needs it. |

Talk to brokers through a thin **`BrokerAdapter`** interface. Use `requests` against
the REST APIs; no broker SDK dependency unless explicitly approved.

```
BrokerAdapter
  get_account() -> Account            # equity, cash, buying power
  get_positions() -> list[Position]
  get_open_orders() -> list[Order]
  submit(order: OrderIntent) -> OrderAck
  cancel(order_id) / cancel_all()
  get_fills(since) -> list[Fill]
  clock() -> MarketClock              # open/closed, next open/close
```

Implementations: `SimBroker` (backtests and tests), `AlpacaBroker(mode=paper|live)`,
and later `IbkrBroker`.

## Daily order flow

```
data lands (GitHub Action / client host)
  → integrity check (coverage, staleness)          fail → no trading today, alert
  → score universe (frozen model + config hash)
  → target portfolio (top-k, buffer rule)
  → diff vs current positions → OrderIntents
  → RISK ENGINE (hard limits below)                 any breach → block + alert
  → submit before the open (market-on-open or limit at a reference price)
  → reconcile fills vs intents after the open        mismatch → alert
  → log: intents, acks, fills, slippage vs model    (private store)
```

The decision uses the data of session *d*; the orders fill at the open of *d+1*. This
is the same lag the evaluation protocol assumes (E1), so live results are comparable
to the backtest.

## Risk engine — hard limits (defaults, per account, set in the private live config)

| Limit | Default | Action on breach |
|---|---|---|
| Max position weight | 5% of equity | clip the order |
| Max gross exposure | 100% (no leverage) | block the order |
| Max number of orders per day | 2 × k | block the rest, alert |
| Max single order notional | 10% of equity | block |
| Price-band check | limit price within ±3% of the reference | block |
| Allowed symbols | the current universe only | block |
| No shorting, no options, no margin | on | block |
| Daily loss vs prior close | −3% | **kill switch** |
| Drawdown from high-water mark | −15% | **kill switch**, manual review |
| Data staleness | latest bar older than 1 session | no trading today |
| Broker/model position mismatch | any | no new orders until reconciled |

**Kill switch:** cancel all open orders, block new ones, alert, and require a manual
reset (a signed-off entry in the private ops log). Positions are **not** auto-liquidated;
a human decides. A `KILL` file or env flag on the host also triggers it.

## Client deployments

- One isolated deployment per client: their own VPS or cloud account, their own
  secrets, their own logs and database. Nothing shared across clients.
- The deployment pulls a **tagged release** of the public code plus the private strategy
  artifact. It never runs `main` directly.
- The client's broker key has trading permission only (no withdrawals), with an IP
  allow-list to the deployment host where the broker supports it.
- A daily report to the client covers positions, orders, fills, slippage vs model, risk
  events and data health, delivered privately (email or the client's portal), never in
  the public repo or its logs.
- Onboarding checklist: legal structure agreed, risk limits signed off by the client, a
  paper period on the client's own paper account, then live with a reduced size
  (25%) for the first month.

## Execution gate (before any live money)

1. The strategy passed the research gate and its pre-registered paper holdout.
2. 20+ consecutive paper sessions with zero unexplained intent/fill mismatches.
3. Realised slippage vs the cost model: median within the stress-cost assumption.
4. Kill switch tested: injected daily loss → orders cancelled, trading blocked, alert received.
5. Restart test: host killed mid-day → state rebuilt from the broker, no duplicate orders.
6. Client limits configured and confirmed in writing.
