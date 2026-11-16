# asset-copilot

Evaluated AI agent for commercial real estate portfolio analysis: text-to-SQL + document RAG with citations, variance reporting, and audit logging.

> Built on **synthetic and public data only**. No confidential or proprietary data is used.

## Architecture

```
Streamlit UI ──► FastAPI ──► Agent (Claude tool use)
                               ├─ run_sql        → SQL guard (sqlglot) → read-only Postgres role
                               ├─ search_docs    → pgvector retrieval over lease/loan documents
                               └─ calculate      → deterministic math (no LLM arithmetic)
                             Every action → audit_log;  user ratings → feedback
```

## Governance

- Single-statement `SELECT` only, table allow-list, automatic `LIMIT` (`governance.py`)
- Dedicated read-only DB role with a statement timeout (`db/roles.sql`)
- Audit log of every query and agent action

## Quickstart

```bash
cp .env.example .env            # add ANTHROPIC_API_KEY
docker compose up -d            # Postgres + pgvector, schema and roles auto-applied
pip install -e ".[dev]"
python -m asset_copilot.synth.generate --properties 60 --seed 42
uvicorn asset_copilot.api:app --reload
streamlit run app/streamlit_app.py
pytest
```

## Docs

- [`docs/ROADMAP.md`](docs/ROADMAP.md): milestones with acceptance criteria
- [`docs/EVALS.md`](docs/EVALS.md): evaluation plan, categories, and metrics
- [`docs/JOB_CONTEXT.md`](docs/JOB_CONTEXT.md): the skills this project is meant to demonstrate
- [`CLAUDE.md`](CLAUDE.md): conventions and rules for AI-assisted development

## Status

- [x] Schema, synthetic data generator, SQL governance layer, API + UI skeleton
- [ ] Agent loop with SQL tool and citations
- [ ] Document ingestion + retrieval
- [ ] Variance report workflow
- [ ] Eval harness with measured accuracy
- [ ] Stakeholder memo and demo video
