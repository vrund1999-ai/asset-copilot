# asset-copilot

Evaluated AI agent for commercial real estate (CRE) portfolio analysis. Answers questions across
structured data (Postgres) and unstructured documents (leases, loan docs) with citations.
It is a portfolio/resume project demonstrating production-quality applied AI: reliability,
governance, and measured accuracy. Read `docs/ROADMAP.md` for what to build and
`docs/JOB_CONTEXT.md` for why.

## Stack

Python 3.11+, FastAPI (`src/asset_copilot/api.py`), Streamlit (`app/streamlit_app.py`),
Postgres 16 + pgvector (Docker), SQLAlchemy, sqlglot, Anthropic API (default model set in
`config.py` / `.env`).

## Commands

```bash
cp .env.example .env                 # then add ANTHROPIC_API_KEY (never commit .env)
docker compose up -d                 # Postgres; applies db/schema.sql and db/roles.sql on first start
python -m venv .venv && pip install -e ".[dev]"
python -m asset_copilot.synth.generate --properties 60 --seed 42   # (re)load synthetic data; truncates tables
uvicorn asset_copilot.api:app --reload
streamlit run app/streamlit_app.py
pytest                               # unit tests (no DB needed)
ruff check .
python evals/run_evals.py            # eval harness
```

Schema changes: edit `db/schema.sql`, then `docker compose down -v && docker compose up -d`
(init scripts only run on an empty volume), and regenerate data.

## Architecture rules (do not violate)

- The agent's SQL runs ONLY through `db.run_readonly_query`: it validates with `governance.validate_sql`
  and executes on the `agent_ro` role. Never give the agent the admin connection.
- The LLM never does arithmetic. Numbers come from SQL or the `calculate` tool.
- Every answer must carry citations (executed SQL and/or document + page). No citation, no claim.
- Every agent action is written to `audit_log` via `db.audit`.
- Keep `ALLOWED_TABLES` in `governance.py` and the grants in `db/roles.sql` in sync.

## Data and confidentiality rules

- Synthetic or public data only. Never add confidential or proprietary data.
- Do not name any specific employer or firm in the repo name, README, code, docs, or data.
  The target role is discussed only in `docs/JOB_CONTEXT.md`, in generic terms.

## Workflow rules

- Never push or commit directly to `main`. Work on a feature branch, push it, and open a PR
  with `gh pr create`. Do not merge; the owner reviews and merges.
- No AI-attribution lines (no "Co-Authored-By", no "Generated with ...") in commits, PR titles,
  PR bodies, issues, or code comments.
- Add or update tests with each change. Governance changes need tests for both allowed and blocked queries.
- When a roadmap item is finished, tick it in `README.md` Status and `docs/ROADMAP.md`.
