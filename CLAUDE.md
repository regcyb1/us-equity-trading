# CLAUDE.md — US Equity Algorithmic Trading

This repo is **PUBLIC**. Read `docs/SECURITY.md` before your first commit in any session.
Read `docs/PLAN.md` to find the current phase, then only the doc the task needs.
`docs/ARCHITECTURE.md` is the source of truth for contracts.

## Security rules (highest priority)

1. Never write a secret, key, token, password, account number or client detail into
   any file, commit message, issue, PR, log line or test. Read secrets only from
   environment variables via `config/secrets.py`.
2. Never print or log secret values, market data rows, account values or client
   identifiers in CI. Actions logs in this repo are public. Print counts and statuses only.
3. Never commit data or artifacts (`.parquet`, `.csv`, `.pkl`, `.joblib`, `.db`, `.env`).
   Test fixtures are synthetic and live in `tests/fixtures/`.
4. Never use `pull_request_target`. Every workflow declares `permissions:`. Pin
   actions to a commit SHA.
5. Never commit absolute home paths, personal emails or machine names.
6. If you find a leaked secret: stop, tell the user to revoke and rotate it first, then
   clean the history. Revocation comes before any code fix.
7. Before committing, run `pre-commit run --all-files`. Never bypass hooks (`--no-verify`).

## Trading safety rules

8. Default `TRADING_MODE=paper`. Never write code that reaches the live broker host
   unless the task explicitly says live, and never enable live trading yourself.
9. All orders go through the risk engine. No code path may call a broker `submit`
   directly.
10. Never weaken a risk limit or the kill switch without explicit user approval.

## Project rules

11. Do not add fields outside `contracts/schema.py`; change ARCHITECTURE.md first.
12. New features are registered in `contracts/registries.py` `FEATURE_REGISTRY` first.
13. No new dependencies unless requested. Allowed: pandas, numpy, pyarrow, duckdb,
    scikit-learn, xgboost, requests, pyyaml, pytest; dev: pre-commit, pip-audit.
14. Pure functions everywhere except `ingest/`, `pipelines/`, `execution/`.
15. A required-column check on every dataframe input. Preserve signatures unless required.
16. Smallest safe change. No refactor mixed with feature work.

## Data rules

17. `data/raw/` is append-only. Writes are keyed and idempotent; a write that shrinks history raises.
18. Every HTTP call goes through `ingest/http.py` (rate limit, retry, timeout, TLS on, raw archive).
19. SEC: ≤5 requests/s with a User-Agent that includes a contact email (taken from env).
20. Do not fill missing prices. Point-in-time only (`available_from` ≤ row date).

## Evaluation rules

21. Entry lag ≥ 1 in every backtest, as an explicit parameter. Out-of-fold results only.
22. Report rank IC and net-of-cost returns vs the best baseline. Never headline accuracy.
23. Log every tried configuration in the variant registry.
24. Never open the historical vault, change a pre-registered test, or retrain during a
    holdout without explicit user approval.

## Output style

25. Changed files only; short explanations; risks only if real; smallest test command.
26. If unsure about a broad change, ask first.
