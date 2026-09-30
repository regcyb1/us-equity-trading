# Security model — public repo

The code repo is public. Assume everything committed is read by bots within minutes,
forever, including in git history, forks, Actions logs and issue text. Deleting a
leaked secret from the repo does **not** un-leak it. Rotate it.

## 1. What may never be in the public repo

| Category | Examples | Where it lives instead |
|---|---|---|
| Secrets | data API keys, broker keys, PATs, SSH/deploy keys, Telegram bot tokens, webhook URLs | GitHub Actions **secrets**; local `.env` (gitignored); the client's own secret store |
| Client information | names, emails, account numbers, positions, P&L, contracts | the client's deployment only |
| Market data | raw API responses, parquet, CSV exports, vendor-derived tables | private data repo or bucket. Vendor terms usually **forbid redistribution** |
| Trained artifacts | `*.joblib`, `*.json` model dumps, OOF score files | private artifacts repo or bucket |
| Live strategy parameters | the frozen live config, thresholds, universe overrides | `us-equity-private`, loaded at runtime |
| Personal data | home paths, personal email, phone, IPs, machine names | nowhere. Use relative paths and role names |
| Notebook outputs | cells that print data, keys or paths | strip outputs before commit |

What **is** public: code, tests with synthetic fixtures, docs, example configs with
placeholder values (`configs/*.example.yaml`), research write-ups with aggregate
metrics only.

## 2. Controls, all set up in Phase 0 before the first real key exists

### Git-level
- `.gitignore` from day one (template below).
- **pre-commit hooks**: `gitleaks` (secrets), `detect-private-key`, `check-added-large-files`
  (max 500 KB), `nbstripout` if notebooks are used, and a custom hook that blocks
  `*.parquet`, `*.csv`, `*.joblib`, `*.pkl`, `.env*` except `.env.example`.
- GitHub **secret scanning + push protection** turned on (free for public repos).
- **Branch protection** on `main`: pull requests only, CI must pass, no force push.
- Signed commits, recommended.

### CI-level (`.github/workflows/`)
- Every workflow declares `permissions:` explicitly, defaulting to `contents: read`.
- **Never use `pull_request_target`** or run untrusted fork code with secrets. Secrets
  are only used in `schedule` and `workflow_dispatch` jobs on `main`.
- Pin third-party actions to a **full commit SHA**, not a tag.
- A `gitleaks` job on every push and pull request, as a second line after pre-commit.
- **Actions logs are public in a public repo.** Jobs print counts and statuses only,
  never data rows, keys, account values or client identifiers. Use `::add-mask::` for
  any derived sensitive value.
- Writing to the private data repo: a **fine-grained PAT** scoped to that one repo with
  `contents: write`, or a deploy key. Never a classic PAT with broad scope.
- Dependabot (security updates) + `pip-audit` in CI. CodeQL (free for public repos).

### Code-level
- Keys are read only from environment variables through one module (`config/secrets.py`)
  that raises if a key is missing and **never logs values**. `repr()` of any object
  holding a key returns `***`.
- The logging formatter redacts known key patterns and anything matching the names
  of loaded secrets.
- HTTP client: TLS verification always on (unlike NEPSE's scraper). Timeouts on every call.
- Paper and live broker credentials use **different variable names**
  (`ALPACA_PAPER_KEY_ID`, `LIVE_BROKER_KEY_ID`) and different hosts. Live code refuses
  to start unless `TRADING_MODE=live` **and** a confirmation file exists on that host.
- Broker keys: **trading-only permissions, never withdrawal or transfer**, and an IP
  allow-list where the broker supports it.

### Operational
- Rotate data API keys every 6 months, and immediately after any suspected leak.
- Leak response: revoke → rotate → check provider logs for use → purge from history
  (`git filter-repo`) → force-push → note it in the decision log. Revocation comes first.
- Client deployments: one isolated deployment per client (their own cloud account or
  VPS), their own secrets, their own logs. No shared database across clients.
- Enable 2FA on GitHub, every data provider and every broker account.

## 3. `.gitignore` template (day one)

```gitignore
# secrets
.env
.env.*
!.env.example
*.pem
*.key
secrets/
# data and artifacts — never public
data/
artifacts/
models/*.joblib
*.parquet
*.csv
*.pkl
*.joblib
*.db
*.sqlite
# live / private configs
configs/live/
configs/*.local.yaml
# notebooks and caches
.ipynb_checkpoints/
__pycache__/
.venv/
.DS_Store
# logs can contain data
logs/
*.log
```

Test fixtures that must be CSV live under `tests/fixtures/` with an explicit
`!tests/fixtures/*.csv` exception, and are synthetic.

## 4. `.pre-commit-config.yaml` (day one)

```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: <pin current release tag or SHA>
    hooks:
      - id: gitleaks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: <pin current release>
    hooks:
      - id: detect-private-key
      - id: check-added-large-files
        args: ["--maxkb=500"]
      - id: end-of-file-fixer
      - id: trailing-whitespace
  - repo: local
    hooks:
      - id: block-data-files
        name: block data/artifact files
        entry: "Data or artifact files must not be committed"
        language: fail
        files: '\.(parquet|csv|pkl|joblib|db|sqlite)$|(^|/)\.env($|\.)'
        exclude: '^tests/fixtures/|\.env\.example$'
```

## 5. Security gate (end of Phase 0)

- [ ] A commit containing a fake AWS-style key is blocked locally **and** by CI.
- [ ] A commit containing a `.parquet` file is blocked.
- [ ] `git log -p | gitleaks detect --pipe` is clean.
- [ ] Push protection is on (repo settings screenshot in the decision log).
- [ ] Every workflow has explicit `permissions:`; no `pull_request_target`; actions pinned by SHA.
- [ ] `secrets.py` tests: a missing key raises; `repr` and logs never show the value.
