# asset-copilot

Evaluated AI agent for commercial real estate (CRE) portfolio analysis. Answers questions across
structured data (Postgres) and unstructured documents (leases, loan docs) with citations.
It is a portfolio/resume project demonstrating production-quality applied AI: reliability,
governance, and measured accuracy. Read `docs/ROADMAP.md` for what to build and
`docs/SKILLS_DEMONSTRATED.md` for why.

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
python -m asset_copilot.synth.documents --seed 42      # write lease/loan docs + manifest.json to data/generated/
pip install -e ".[embeddings]" && python -m asset_copilot.ingest   # embed (local model) and load documents/chunks
uvicorn asset_copilot.api:app --reload
streamlit run app/streamlit_app.py
pytest                               # unit tests (no DB needed)
ruff check .
python evals/run_evals.py            # eval harness (needs the API running)
python evals/retrieval_eval.py       # retrieval hit-rate@k for document questions (no LLM)
python evals/compare_runs.py         # before/after table for the two latest full runs
python evals/feedback_report.py      # summarise thumbs up/down + corrections from the feedback table
python evals/make_doc_questions.py --write   # regenerate the q031+ document questions
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
  Do not reference any specific job posting, role, or hiring process; keep all docs generic.

## Workflow rules

- Never push or commit directly to `main`. Work on a feature branch, push it, and open a PR
  with `gh pr create`. Do not merge; the owner reviews and merges.
- No AI-attribution lines (no "Co-Authored-By", no "Generated with ...") in commits, PR titles,
  PR bodies, issues, or code comments.
- Pull request descriptions must follow `.github/pull_request_template.md` and be written for a
  reviewer who has not seen the conversation. See "Pull request standards" below.
- Add or update tests with each change. Governance changes need tests for both allowed and blocked queries.
- When a roadmap item is finished, tick it in `README.md` Status and `docs/ROADMAP.md`.

## Pull request standards

Every PR needs a description a reviewer can act on without reading the chat history.

**Description must include**
- **Summary**: what changed and why, in a few sentences. Link the roadmap milestone (e.g. "M1").
- **Changes**: bullet list of the notable files/behaviors changed. Call out schema changes,
  new env vars, new dependencies, and anything that needs `docker compose down -v` or a data regen.
- **Design notes / tradeoffs**: decisions a reviewer might question, and alternatives rejected.
- **Testing evidence** (below). "Tests pass" alone is not evidence.
- **Risks and follow-ups**: known gaps, limitations, and what is deliberately left for later.

**Testing evidence, by change type**
- **Backend / API / agent**: show the actual calls and results. Include the request (curl or
  httpx), the response body, and the relevant log or `audit_log` rows. For agent changes, show
  one or two representative question -> answer -> citation traces, and the eval run
  (per-category accuracy, before/after if the change affects accuracy).
- **Database / schema / data generator**: show the migration or reload command, `\dt` or a
  verifying query, and row counts or a sample query result.
- **UI (Streamlit)**: include screenshots of the changed states (happy path and at least one
  error or empty state). Save screenshots locally and tell the user which files to attach to the
  PR, because the `gh` CLI cannot upload images. Screenshots meant to stay in the repo
  (README hero images, demo GIFs) go in `docs/screenshots/` and are linked by relative path.
- **Governance / security**: show allowed and blocked cases, e.g. the blocked query and the error returned.
- **Docs-only**: say so; no test evidence needed beyond a link check.
- Always include the output of `pytest` and `ruff check .`. If something was not tested (for
  example, no API key available), say so explicitly instead of implying it was.

**Hygiene**
- Redact secrets (API keys, passwords) and trim long logs to the lines that matter, in a
  collapsed `<details>` block if long.
- Keep PRs focused: one milestone item or one logical change per PR.
- Report outcomes faithfully. If a check failed or a case is flaky, state it in the PR.
