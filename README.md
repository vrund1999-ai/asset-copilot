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
python -m asset_copilot.synth.generate --properties 60 --seed 42   # dates anchor to AS_OF_DATE (default 2026-06-30)
uvicorn asset_copilot.api:app --reload
streamlit run app/streamlit_app.py
pytest
```

## Results

Latest full run of `python evals/run_evals.py` (112 questions, model `claude-sonnet-5-5`, seed 42 data):

| Category | Before | After |
|---|---|---|
| sql_aggregate | 31/31 | 31/31 |
| sql_filter_rank | 19/20 (95%) | 20/20 (100%) |
| lease_rollover | 15/15 | 15/15 |
| document_lookup | 8/8 | 8/8 |
| hybrid | 6/6 | 6/6 |
| reconciliation | 12/12 | 12/12 |
| refusal | 10/10 | 10/10 |
| adversarial | 10/10 (no data modified) | 10/10 (no data modified) |
| **Overall** | **111/112 (99%)** | **112/112 (100%)** |

Answerable questions wrongly refused: 0. Ungrounded answers: 0 (before: 1). Average latency 5.2 s,
165k tokens for the whole run.

**Improvement driven by an eval failure.** The first run of the expanded set failed q087 ("which 5
active leases have the highest base rent per sq ft, with property and suite"). The agent's answer was
correct, but two defects were hiding behind the failure: (1) the grounding check ignored numbers that
appear inside text cells of a cited result ("Suite 10"), so a correct answer was flagged as
ungrounded; (2) the eval scorer located ordered rows by substring, so "Suite 1" matched inside
"Suite 10" and a repeated property name always matched its first occurrence. Both are fixed with
regression tests; q087 is the only question that changed between runs. Compare any two runs with
`python evals/compare_runs.py`.

**Read these numbers with care.** The set is synthetic and was written by the project author, the data
is generated, and categories are at 100%, so the set no longer separates good from bad changes. It is
a regression net and a way to catch scorer bugs, not evidence of general accuracy. Document question
categories are below their target size (see `docs/EVALS.md`). Next useful step: harder, adversarially
worded questions, ideally seeded from thumbs-down feedback (`python evals/feedback_report.py --export`).

## Docs

- [`docs/ROADMAP.md`](docs/ROADMAP.md): milestones with acceptance criteria
- [`docs/EVALS.md`](docs/EVALS.md): evaluation plan, categories, and metrics
- [`docs/SKILLS_DEMONSTRATED.md`](docs/SKILLS_DEMONSTRATED.md): the skills this project is meant to demonstrate
- [`CLAUDE.md`](CLAUDE.md): conventions and rules for AI-assisted development

## Status

- [x] Schema, synthetic data generator, SQL governance layer, API + UI skeleton
- [x] Agent loop with SQL tool and citations
- [x] Document ingestion + retrieval
- [x] Variance report workflow
- [x] Eval harness with measured accuracy
- [ ] Stakeholder memo and demo video
