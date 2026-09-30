# Start prompt

Paste the block below as the first message of a new Claude Code session, run from
inside the new, empty repo folder. Put the planning docs in first:

```
us-equity-trading/
  CLAUDE.md                 <- from this pack
  docs/                     <- every other .md from this pack
```

Then paste:

---

```
You are the lead engineer building a US equity algorithmic trading system from scratch.
This repo will be PUBLIC on GitHub, so security comes before features.

Read, in this order, before writing any code:
1. CLAUDE.md
2. docs/README.md
3. docs/SECURITY.md
4. docs/PLAN.md (Phase 0 and Phase 1 only)
5. docs/ARCHITECTURE.md

Today's task: Phase 0 (foundation + security) only. Do not start Phase 1.

Do it in this order, one small commit per step, running tests after each:

1. git init (if needed), .gitignore and .pre-commit-config.yaml exactly as in
   docs/SECURITY.md sections 3-4 (pin hook versions to current releases), .env.example
   with placeholder variable names only. Install pre-commit hooks.
2. Prove the guards work BEFORE anything else: try to commit (a) a file containing a
   fake token generated at runtime in GitHub PAT format ("ghp_" + 36 random
   alphanumerics; well-known documented example keys may be allowlisted, so don't use
   those) and never written into any doc or script, and (b) a dummy .parquet
   file. Both commits must be blocked. Show me the blocked output, then remove the
   test files. Never commit them.
3. pyproject.toml (Python 3.11, pinned deps from CLAUDE.md), package skeleton per
   docs/ARCHITECTURE.md (empty modules with docstrings only, no logic yet).
4. config/secrets.py: load keys only from environment variables; raise a clear error
   naming the missing variable (never its value); objects holding keys have a redacting
   __repr__; a logging filter that masks loaded secret values. Tests for all three.
5. ingest/http.py: one client with per-source rate limiting, retry with exponential
   backoff, timeouts, TLS verification on, a configurable User-Agent from env, and a
   raw-archive write (gzipped response + request metadata, secrets stripped from the
   saved URL/headers) BEFORE returning. Tests use a fake transport, no network.
6. contracts/schema.py: validators for the silver tables in docs/ARCHITECTURE.md
   (required columns, dtypes, key uniqueness, available_from <= date). Tests with
   synthetic fixtures.
7. .github/workflows/tests.yml: on push and pull_request, permissions: contents: read,
   actions pinned by full commit SHA, steps: pytest, gitleaks, pip-audit. No secrets
   used. Add codeql.yml and dependabot.yml.
8. docs/decision_log.md: first entries = the decisions in docs/README.md, dated today.

Rules for this session:
- Never ask me to paste a key into the chat. When a key is needed, tell me the
  environment variable name and I will set it myself.
- Do not create any file containing real data, real keys, my home path or my email.
- Do not add dependencies beyond CLAUDE.md.
- After each step: list changed files, show the test command and its result.

Finish by walking through the Phase 0 gate (docs/PLAN.md) and the security gate
(docs/SECURITY.md section 5). Mark each item pass, fail or needs-me. List what I must
do by hand in GitHub settings (push protection, branch protection, secrets) as a
checklist. Then stop and wait for me.
```

---

## Follow-up prompts, one per phase

Use these when the previous gate passes. Each starts a fresh session.

**Phase 1:**
> Read CLAUDE.md, docs/SECURITY.md and docs/PLAN.md Phase 1. Build the forward
> collector (Nasdaq symbol directory, Massive grouped daily, FRED, S&P 500 membership),
> the NYSE holiday check and `.github/workflows/collect.yml` writing to the private
> data repo with a repo-scoped token. Logs print counts only. Stop at the Phase 1 gate.

**Phase 2:**
> Read CLAUDE.md, docs/DATA_SOURCES.md and docs/PLAN.md Phase 2. Build the security
> master, multi-source price reconciliation, corporate actions, delistings and the
> coverage report. Never fill gaps. Stop at the coverage gate and show the report.

**Phases 3–5:**
> Read CLAUDE.md, docs/EVALUATION_PROTOCOL.md and docs/PLAN.md Phase N. Implement
> exactly that phase. Baselines before models. Log every variant. Stop at the gate
> with the full metric table.

**Phase 6:**
> Read CLAUDE.md, docs/EXECUTION_AND_RISK.md and docs/PLAN.md Phase 6. Build the
> BrokerAdapter, SimBroker, AlpacaBroker in paper mode only, the risk engine and the
> kill switch, with tests that inject breaches. Write the pre-registration before the
> first paper order. Never touch the live host.
