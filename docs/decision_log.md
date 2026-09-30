# Decision log

Dated decisions and anything that changes a contract. Newest last. Never edit an old
entry; add a new one that supersedes it.

## 2026-09-30 — Founding decisions (from docs/README.md)

1. **Separate repo.** The NEPSE system is in a forward holdout until ~2027-03 and its
   code is NEPSE-specific. Pure research modules are copied, not imported. A shared
   package (`quantcore`) is extracted later.
2. **Public code, private everything else.** Code is public. Data, keys, client
   information, trained models and live strategy parameters live outside the repo
   (`SECURITY.md`), enforced by tooling, not memory.
3. **Start the forward collector on day one.** Forward data is survivorship-free by
   construction and free. Every week of delay is data lost for good.
4. **Free-only, multi-source, reconciled data.** No single free source is complete.
   Cross-check every price and publish a coverage report.
5. **Baselines before models; kill criteria before results.** A model matters only if
   it beats simple factors net of costs at a realistic entry lag.
6. **Risk engine is independent of the strategy.** Every order passes hard limits and a
   kill switch that the strategy code cannot bypass.

## 2026-09-30 — Phase 0 build decisions

7. **Dependency pins for Python 3.11.** numpy 2.5.x and xgboost ≥3.3 require Python
   3.12, so they are pinned to numpy 2.4.6 and xgboost 3.2.0, the newest releases
   that support 3.11. All other allowed deps are pinned to their current release.
8. **CI gitleaks runs the release binary, checksum-verified**, not `gitleaks-action`.
   This needs no token and no licence, and the SHA-256 pin gives the same supply-chain
   guarantee as pinning an action by commit SHA.
9. **Raw archive partition = UTC fetch date.** `raw/<source>/<yyyy>/<mm>/<dd>/` is the
   date the response was fetched (UTC), not the market session date. Files are
   created exclusively; an identical re-fetch is a no-op, a changed body gets a
   timestamp-suffixed file. Nothing is overwritten.
10. **Secrets stripped from the archive include the User-Agent**, because it carries a
    contact email. Query params and headers whose names contain key/token/secret/
    password/auth/signature/cookie are masked, plus any value loaded via
    `config/secrets.py`. URL userinfo is dropped.
11. **Schema errors report counts, never values**, so a failed validation in public CI
    logs cannot leak data rows.
12. **Guard proof used a GitHub-PAT-format token** generated at runtime (per
    START_PROMPT), in addition to the AWS-style key named in `SECURITY.md` §5. Both
    formats are covered by gitleaks default rules.
13. **Commit author identity.** The machine's global git email is personal. No commits
    are made until a repo-local GitHub noreply address is configured.

## 2026-09-30 — Phase 0 gate deferred

14. **Phase 1 starts before the Phase 0 gate passes.** User decision: build the system
    locally first, git and GitHub later. Open gate items (CI green, CI blocks a fake
    key, history scan, push/branch protection) are re-checked before the first push.
    Phase 1 parts that need git (`collect.yml`, commits to `us-equity-data`) wait too;
    the collector writes to local `data/` (gitignored) meanwhile.

## 2026-09-30 — Phase 1 build decisions

15. **NYSE calendar is YAML, not CSV** (`configs/nyse_calendar.yaml`): `*.csv` is blocked
    by the hooks outside `tests/fixtures/`. Covers 2026–2028 from nyse.com; any other
    year raises `CalendarRangeError` (fail closed). Add 2005–2025 before Phase 2 backfill.
16. **Massive key goes in an `Authorization: Bearer` header**, never the URL query.
17. **Membership files: a date listed twice with different ticker lists is dropped**
    (both rows), and the count is logged. First live run: hanshof has 2 such dates.
18. **hanshof is stale** (last snapshot 2025-08-23, 403 days old on first run).
    fja05680 is the only current membership source; Wikipedia changes table is the
    intended third check (Phase 2). Staleness > 45 days is logged, not a failure.
19. **Collector skips work already done**: a session already in bronze makes no
    Massive call; membership is pulled at most weekly. Integrity failure (row count
    ±5% vs previous session, duplicate keys, close ≤ 0) blocks the bronze write and
    exits non-zero; the raw response is still archived.
20. **Deferred with git**: `collect.yml` and commits to `us-equity-data`.
