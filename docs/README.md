# US Equity Algorithmic Trading System — planning pack

An algorithmic system that researches, paper-trades and (for clients abroad)
live-trades US equities. It is built with the evaluation discipline learned on the
NEPSE system, as a **separate public repo**.

**Status:** planning. Nothing built yet. Written 2026-09-30.

## Read in this order

| File | What it answers |
|---|---|
| `README.md` | What this is, the operating model, the one-page summary |
| `START_PROMPT.md` | The prompt that starts the first build session |
| `PLAN.md` | Phases, tasks, gates, kill criteria, timeline |
| `SECURITY.md` | Public-repo security model: what may never be committed, and the controls that enforce it |
| `DATA_SOURCES.md` | Free US data sources, their limits, and how they combine into one reliable dataset |
| `ARCHITECTURE.md` | Repo layout, data layers, schemas, pipelines, scheduling, storage |
| `EVALUATION_PROTOCOL.md` | Rules every result must follow before anyone believes it |
| `EXECUTION_AND_RISK.md` | Broker adapters, order flow, risk limits, kill switch, client deployments |
| `CLAUDE.md` | Rules for coding agents (copy to the repo root) |

## Operating model

```
research  →  paper trading (your own Alpaca paper account)  →  live, client accounts only
```

- **You build and operate the software. Clients own the brokerage accounts.** Each
  client's account and API keys stay in that client's own deployment. They never
  enter this repo, your laptop's git history or a shared server.
- **Paper first, always.** No strategy reaches a client account until it has passed
  the research gate and a pre-registered paper-trading holdout.
- **Compliance is the client's jurisdiction.** In the US, managing other people's
  accounts or giving personalised advice for a fee can require registration (for
  example as an investment adviser). Before the first paying client, get advice in
  the client's jurisdiction on the structure: software licence vs signals vs
  managed account.
- Personal note: Nepal restricts residents from investing abroad themselves (Foreign
  Exchange (Regulation) Act 2019, s.10A). Building and operating software for
  foreign clients is a different activity. Keep your own trading on paper unless
  approved.

## The six decisions this plan rests on

1. **Separate repo.** The NEPSE system is in a forward holdout until ~2027-03 and its
   code is NEPSE-specific. Pure research modules are copied, not imported. A shared
   package is extracted later.
2. **Public code, private everything else.** Code is public (portfolio value, free CI).
   Data, keys, client information, trained models and live strategy parameters live
   outside the repo. See `SECURITY.md`. This is enforced by tooling, not by memory.
3. **Start the forward collector on day one.** Forward data is survivorship-free by
   construction and free. Every week of delay is data lost for good.
4. **Free-only, multi-source, reconciled data.** No single free source is complete.
   Cross-check every price and publish a coverage report.
5. **Baselines before models; kill criteria before results.** US markets are
   efficient. A model matters only if it beats simple factors net of costs at a
   realistic entry lag.
6. **Risk engine is independent of the strategy.** Every order passes hard limits and
   a kill switch that the strategy code cannot bypass.

## Repos and storage at a glance

| Thing | Where | Visibility |
|---|---|---|
| Code, docs, tests, CI | `us-equity-trading` (GitHub) | **public** |
| Market data, raw archive | `us-equity-data` (GitHub) or a B2/R2 bucket | **private** |
| Trained models, live strategy configs | `us-equity-private` (GitHub) or bucket | **private** |
| API keys, broker keys | GitHub Actions secrets + local `.env` | never in git |
| Client keys and data | each client's own deployment and secret store | never leaves it |
