# Roadmap

Target: ~4-5 weeks of evenings. Each milestone lists acceptance criteria ("done when"). Tick the
box when met. Prefer finishing one thing well over breadth.

## M0. Scaffold (done)

- [x] Schema, read-only role, synthetic generator, SQL guard + tests, API/UI skeleton, CI, eval stub

## M1. SQL agent with citations (week 1-2)

Implement `agent.py` (Claude tool use loop) and wire it to `POST /ask`.

Tools:
- `run_sql(sql)`: calls `db.run_readonly_query`; returns rows (capped) or the guard's error so the model can retry.
- `calculate(expression)`: safe arithmetic evaluator (no `eval`); used for any derived number.
- Tool-use loop with a max-iterations cap (e.g. 8) and a clear failure message when exceeded.
- System prompt includes a compact schema description (tables, columns, units, "month = first day of month").

Response contract (`AskResponse`): `answer` text plus `citations` of `{kind: "sql"|"document", reference}`.
For SQL, `reference` is the executed query. The answer must not state a number that did not come from a tool result.

Done when:
- [ ] `/ask` answers the SQL questions in `evals/questions.jsonl` end to end via the Streamlit UI
- [ ] Every response includes at least one citation; uncitable questions return "I can't determine that from the data"
- [ ] Unsafe model-generated SQL is blocked and the error is fed back (covered by a test with a mocked model)
- [ ] Each tool call and final answer is in `audit_log` with the session id
- [ ] Unit tests with a mocked Anthropic client (no network in CI)

## M2. Documents: generation, ingestion, retrieval (week 2-3)

- Generate synthetic lease abstracts / lease text (2-4 pages each) for a subset of leases, consistent with
  the `leases` table values (rent, term, renewal options) plus a few deliberate discrepancies for
  reconciliation tests. Also loan summaries for `debt`. Store as markdown/PDF under `data/generated/` (gitignored); generator must be seeded.
- Ingest: parse, chunk (keep page numbers), embed, load `documents` + `document_chunks`
  (`vector(1024)` in schema; change the dimension in `db/schema.sql` if the chosen embedding model differs).
- `search_documents(query, property_id?)` tool returning passages with `document title` and `page`.
- Extend the agent to combine SQL and document evidence. Citations: `kind: "document"`, `reference: "<title> p.<n>"`.
- Reconciliation: flag when a document's stated value disagrees with the database (e.g. lease end date) instead of silently picking one.

Done when:
- [ ] Hybrid questions ("which assets roll over >20% in 18 months and what do their renewal options say?") answered with both citation kinds
- [ ] At least 5 seeded discrepancies are detected and reported
- [ ] Retrieval hit-rate measured in evals (see `docs/EVALS.md`)

## M3. Variance report workflow (week 3-4)

- Endpoint + UI page: pick a property (or portfolio) and month; compare `operating_statements` vs `budgets`.
- Deterministic calc of revenue/opex/NOI variance ($ and %) in code; LLM only drafts commentary on top of the computed numbers.
- Drivers: identify the largest contributing properties/line items; draft a short commentary; flag items over a threshold for human review.
- Feedback: thumbs up/down and optional correction in the UI -> `POST /feedback` -> `feedback` table.

Done when:
- [ ] Report numbers match a gold SQL calculation exactly (tested)
- [ ] Commentary contains no number absent from the computed tables (checked automatically)
- [ ] Feedback is stored and surfaced in an eval/analysis script

## M4. Evals and hardening (week 4)

See `docs/EVALS.md`. Build the labeled set (target 100+ questions), scoring, per-category accuracy,
and a results history so improvements are visible (before/after table in the README).

Done when:
- [ ] `python evals/run_evals.py` produces per-category accuracy and writes `evals/results/<timestamp>.json`
- [ ] README includes a results table and at least one documented improvement driven by eval failures
- [ ] CI runs unit tests; evals run manually (they need an API key and DB)

## M5. Packaging and communication (week 5)

- [ ] README: architecture diagram, results, governance section, limitations, demo GIF/video
- [ ] `docs/STAKEHOLDER_MEMO.md`: one page for a head of asset management (problem, outcome metrics, risks, rollout plan), no jargon
- [ ] Optional: deploy a hosted demo (synthetic data only)

## Non-goals

- Real or confidential data, authentication/multi-tenancy, a fancy frontend, fine-tuning.
